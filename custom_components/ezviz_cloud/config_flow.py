"""Config flow for EZVIZ Cloud (CN)."""

from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .api import (
    EzvizCloudApi,
    EzvizCloudAuthError,
    EzvizCloudError,
    EzvizCloudMfaRequired,
)
from .const import CONF_ACCOUNT, CONF_PASSWORD, CONF_SERIAL, CONF_TOKEN, DOMAIN

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ACCOUNT): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_SERIAL): str,
        vol.Optional(CONF_TOKEN): str,
    }
)

MFA_SCHEMA = vol.Schema({vol.Required("sms_code"): str})

REAUTH_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_PASSWORD): str,
        vol.Optional(CONF_TOKEN): str,
    }
)


class EzvizCloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._api: EzvizCloudApi | None = None
        self._pending: dict[str, Any] = {}
        self._sms_failed = False
        self._reauth_entry: config_entries.ConfigEntry | None = None

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _parse_token(raw: str | None) -> dict[str, Any] | None:
        raw = (raw or "").strip()
        if not raw:
            return None
        return json.loads(raw)

    async def _finish(self, api: EzvizCloudApi, data: dict[str, Any]) -> FlowResult:
        await self.async_set_unique_id(data[CONF_SERIAL])
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"EZVIZ {data[CONF_SERIAL]}",
            data={
                CONF_ACCOUNT: data[CONF_ACCOUNT],
                CONF_PASSWORD: data[CONF_PASSWORD],
                CONF_SERIAL: data[CONF_SERIAL],
                CONF_TOKEN: api.token,
            },
        )

    # -- first-time setup -------------------------------------------------
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            token = None
            try:
                token = self._parse_token(user_input.get(CONF_TOKEN))
            except ValueError:
                errors["base"] = "invalid_token"

            if not errors:
                api = EzvizCloudApi(
                    user_input[CONF_ACCOUNT],
                    user_input[CONF_PASSWORD],
                    user_input[CONF_SERIAL],
                    token=token,
                    allow_password_login=True,
                )
                try:
                    if token:
                        await self.hass.async_add_executor_job(api.validate)
                    else:
                        await self.hass.async_add_executor_job(api.login)
                except EzvizCloudMfaRequired:
                    self._api = api
                    self._pending = user_input
                    self._sms_failed = not await self._send_sms(api)
                    return await self.async_step_mfa()
                except EzvizCloudAuthError as err:
                    _LOGGER.warning("登录失败: %s", err)
                    errors["base"] = "auth"
                except EzvizCloudError as err:
                    _LOGGER.warning("连接失败: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    return await self._finish(api, user_input)

        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors,
            description_placeholders={"host": "api.ys7.com"},
        )

    async def _send_sms(self, api: EzvizCloudApi) -> bool:
        try:
            await self.hass.async_add_executor_job(api.send_mfa_code)
            return True
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("发送短信验证码失败: %s", err)
            return False

    async def async_step_mfa(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and self._api is not None:
            try:
                await self.hass.async_add_executor_job(
                    self._api.login, user_input["sms_code"]
                )
            except EzvizCloudMfaRequired:
                errors["base"] = "invalid_mfa"
            except EzvizCloudAuthError:
                errors["base"] = "auth"
            except EzvizCloudError:
                errors["base"] = "cannot_connect"
            else:
                if self._reauth_entry is not None:
                    return await self._finish_reauth(self._api)
                return await self._finish(self._api, self._pending)

        if user_input is None and self._sms_failed and not errors:
            errors["base"] = "sms_failed"
        return self.async_show_form(
            step_id="mfa", data_schema=MFA_SCHEMA, errors=errors,
            description_placeholders={
                "account": (self._pending or {}).get(CONF_ACCOUNT, ""),
            },
        )

    # -- reauth -----------------------------------------------------------
    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        entry = self._reauth_entry
        assert entry is not None

        if user_input is not None:
            password = (user_input.get(CONF_PASSWORD) or "").strip() or entry.data.get(
                CONF_PASSWORD
            )
            token = None
            try:
                token = self._parse_token(user_input.get(CONF_TOKEN))
            except ValueError:
                errors["base"] = "invalid_token"

            if not errors:
                api = EzvizCloudApi(
                    entry.data[CONF_ACCOUNT],
                    password,
                    entry.data[CONF_SERIAL],
                    token=token,
                    allow_password_login=True,
                )
                try:
                    if token:
                        await self.hass.async_add_executor_job(api.validate)
                    else:
                        await self.hass.async_add_executor_job(api.login)
                except EzvizCloudMfaRequired:
                    self._api = api
                    self._pending = {
                        **entry.data,
                        CONF_PASSWORD: password,
                        CONF_TOKEN: token,
                    }
                    self._sms_failed = not await self._send_sms(api)
                    return await self.async_step_mfa()
                except EzvizCloudAuthError as err:
                    _LOGGER.warning("重新认证失败: %s", err)
                    errors["base"] = "auth"
                except EzvizCloudError as err:
                    _LOGGER.warning("连接失败: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    return await self._finish_reauth(api)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"account": entry.data.get(CONF_ACCOUNT, "")},
        )

    async def _finish_reauth(self, api: EzvizCloudApi) -> FlowResult:
        entry = self._reauth_entry
        assert entry is not None
        self.hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_TOKEN: api.token}
        )
        return self.async_abort(reason="reauth_successful")
