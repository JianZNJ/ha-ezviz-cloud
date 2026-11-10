"""Thin synchronous wrapper around the CN-fork pyezvizapi client.

Only what this integration needs: login/refresh, privacy switch, PTZ.
The heavy/optional parts of pyezvizapi (MQTT push, CAS streams) are not used.
"""

from __future__ import annotations

import logging
import time
import traceback
from typing import Any

from .pyezvizapi import EzvizClient
from .pyezvizapi.exceptions import EzvizAuthVerificationCode, PyEzvizError

from .const import API_HOST, PRIVACY_CHANNEL, PRIVACY_SWITCH_TYPE

_LOGGER = logging.getLogger(__name__)


class EzvizCloudError(Exception):
    """Base error."""


class EzvizCloudAuthError(EzvizCloudError):
    """Wrong credentials / login rejected."""


class EzvizCloudMfaRequired(EzvizCloudError):
    """Account has SMS MFA enabled; client kept for the second step."""

    def __init__(self, client: EzvizClient) -> None:
        super().__init__("MFA required")
        self.client = client


class EzvizCloudApi:
    """Blocking API — call through hass.async_add_executor_job."""

    def __init__(
        self,
        account: str,
        password: str,
        serial: str,
        token: dict[str, Any] | None = None,
    ) -> None:
        self.account = account
        self.serial = serial
        self._password = password
        self._client: EzvizClient | None = None
        self._token = token
        self._last_refresh = 0.0

    # -- auth -------------------------------------------------------------
    def client(self) -> EzvizClient:
        if self._client is None:
            self._client = EzvizClient(
                self.account,
                self._password or None,
                url=API_HOST,
                token=self._token,
            )
        return self._client

    @property
    def token(self) -> dict[str, Any]:
        if self._client is None:
            return self._token or {}
        return dict(getattr(self._client, "_token", {}) or {})

    def login(self, sms_code: str | None = None) -> None:
        """Full login. Raises EzvizCloudMfaRequired when a code is needed."""
        cl = self.client()
        try:
            cl.login(sms_code=sms_code)
        except EzvizAuthVerificationCode as err:
            raise EzvizCloudMfaRequired(cl) from err
        except (PyEzvizError, ValueError) as err:
            _LOGGER.debug("login failed:\n%s", traceback.format_exc())
            raise EzvizCloudAuthError(str(err)) from err
        pass

    def validate(self) -> None:
        """Check that the saved token still works, without a fresh login."""
        cl = self.client()
        try:
            info = cl.get_device_infos(self.serial)
        except EzvizAuthVerificationCode as err:
            raise EzvizCloudMfaRequired(cl) from err
        except (PyEzvizError, ValueError) as err:
            raise EzvizCloudAuthError(str(err)) from err
        if not info:
            raise EzvizCloudAuthError("empty device_info response")

    def send_mfa_code(self) -> None:
        self.client().send_mfa_code()

    def ensure_login(self) -> None:
        """Only log in from scratch when there is no saved session.

        已有 session 时不做主动刷新：萤石会话有效期很长，由调用失败时的
        _call_with_retry 兜底重登，避免每次启动都撞 /apigateway/login。
        """
        if not self.token.get("session_id"):
            self.login()

    def _call_with_retry(self, func, *args, **kwargs):
        """Run a cloud call; on auth-ish failure refresh once and retry."""
        self.ensure_login()
        try:
            return func(*args, **kwargs)
        except EzvizCloudMfaRequired:
            raise
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("调用失败，尝试重新登录: %s", err)
            self._client = None
            self.login()
            return func(*args, **kwargs)

    # -- data -------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        cl = self.client()
        info = self._call_with_retry(cl.get_device_infos, self.serial)
        switches = {
            str(item.get("type")): bool(item.get("enable"))
            for item in (info.get("SWITCH") or [])
        }
        return {
            "privacy": switches.get(str(PRIVACY_SWITCH_TYPE)),
            "switches": switches,
            "privacyStatus": (info.get("STATUS") or {}).get("privacyStatus"),
        }

    def set_privacy(self, enable: bool) -> None:
        cl = self.client()
        resp = self._call_with_retry(
            cl.device_switch,
            self.serial,
            PRIVACY_CHANNEL,
            1 if enable else 0,
            PRIVACY_SWITCH_TYPE,
        )
        code = (resp.get("meta") or {}).get("code")
        if code != 200:
            raise EzvizCloudError(f"遮蔽切换失败: {resp.get('meta')}")

    # -- ptz --------------------------------------------------------------
    def ptz(self, direction: str, ms: int = 300, speed: int = 5) -> None:
        d = direction.lower()
        if d not in ("up", "down", "left", "right"):
            raise EzvizCloudError(f"不支持的方向: {direction}")
        speed = max(1, min(int(speed), 10))
        ms = max(50, min(int(ms), 5000))
        cl = self.client()
        self._call_with_retry(cl.ptz_control, d.upper(), self.serial, "START", speed)
        try:
            time.sleep(ms / 1000)
        finally:
            for attempt in (1, 2, 3):
                try:
                    cl.ptz_control(d.upper(), self.serial, "STOP", speed)
                    break
                except Exception:  # noqa: BLE001
                    _LOGGER.warning("PTZ STOP 第 %s 次失败", attempt)
                    time.sleep(0.5)
