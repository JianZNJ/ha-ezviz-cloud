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


class EzvizCloudReauthRequired(EzvizCloudAuthError):
    """Saved session is gone and only a human can supply an SMS code."""


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
        allow_password_login: bool = False,
    ) -> None:
        self.account = account
        self.serial = serial
        # 后台绝不允许触发密码登录：萤石对密码登录一律回 MFA，每次尝试都会真的
        # 给账号发一条短信。只有 config_flow（用户在场）才把密码交给客户端。
        self.allow_password_login = allow_password_login
        self._password = password
        self._client: EzvizClient | None = None
        self._token = token
        self._last_refresh = 0.0
        # 会话被云端续期后 token 会变（rf_session_id 轮换）。回调把新 token 写回
        # config entry，否则 HA 重启后拿旧 rf_session_id 续期必然 500。
        self.on_token_update = None
        self._reported_token = dict(token or {})

    # -- auth -------------------------------------------------------------
    def client(self) -> EzvizClient:
        if self._client is None:
            self._client = EzvizClient(
                self.account,
                (self._password or None) if self.allow_password_login else None,
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

        没有 session 时不发密码登录（那会立刻触发短信），而是抛
        EzvizCloudReauthRequired 让 HA 把条目标成「需要重新认证」。
        """
        if not self.token.get("session_id"):
            raise EzvizCloudReauthRequired("没有可用的会话，需要重新认证")

    def _notify_token(self) -> None:
        """把云端轮换后的 token 交给上层持久化（异步回调，失败不影响调用）。"""
        tok = self.token
        if tok == self._reported_token:
            return
        self._reported_token = dict(tok)
        if self.on_token_update is None:
            return
        try:
            self.on_token_update(tok)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("持久化 token 失败:\n%s", traceback.format_exc())

    def _refresh_session(self) -> bool:
        """尽力续期；失败只是返回 False，绝不动现有会话。

        萤石 /v3/apigateway/login 经常整段时间返回 500（服务端故障），此时
        session_id 本身往往仍然有效，丢掉客户端改用密码登录只会触发短信。
        """
        try:
            self.client().login()
        except EzvizAuthVerificationCode:
            _LOGGER.debug("续期需要短信验证码，保留现有会话")
            return False
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("会话续期失败（保留现有会话）: %s", err)
            return False
        self._notify_token()
        return True

    def _call_with_retry(self, func, *args, **kwargs):
        """调用云接口，失败时重试 + 尽力续期；续期失败也不丢会话。"""
        self.ensure_login()
        last: Exception | None = None
        for attempt in range(3):
            try:
                return func(*args, **kwargs)
            except Exception as err:  # noqa: BLE001
                last = err
                _LOGGER.debug("云调用失败（第 %s/3 次）: %s", attempt + 1, err)
                if attempt == 0:
                    self._refresh_session()
                time.sleep(0.8 * (attempt + 1))
        # 最后一次机会：续期成功后再试一遍
        if self._refresh_session():
            try:
                return func(*args, **kwargs)
            except Exception as err:  # noqa: BLE001
                last = err
        text = str(last or "")
        if any(k in text for k in ("401", "403", "身份", "session", "认证")):
            raise EzvizCloudReauthRequired(f"会话已失效: {text}") from last
        raise EzvizCloudError(f"云接口调用失败: {text}") from last

    # -- data -------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        now = time.time()
        if now - self._last_refresh > 1800:
            self._last_refresh = now
            self._refresh_session()
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
