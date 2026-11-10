"""Config flow for EZVIZ Cloud (CN)."""

from __future__ import annotations

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


class EzvizCloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._api: EzvizCloudApi | None = None
        self._pending: dict[str, Any] = {}
        self._sms_failed = False

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            import json

            token = None
            raw_token = (user_input.get(CONF_TOKEN) or "").strip()
            if raw_token:
                try:
                    token = json.loads(raw_token)
                except ValueError:
                    errors["base"] = "invalid_token"

            if not errors:
                api = EzvizCloudApi(
                    user_input[CONF_ACCOUNT],
                    user_input[CONF_PASSWORD],
                    user_input[CONF_SERIAL],
                    token=token,
                )
                try:
                    if token:
                        await self.hass.async_add_executor_job(api.validate)
                    else:
                        await self.hass.async_add_executor_job(api.login)
                except EzvizCloudMfaRequired:
                    self._api = api
                    self._pending = user_input
                    try:
                        await self.hass.async_add_executor_job(api.send_mfa_code)
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.warning("发送短信验证码失败: %s", err)
                        self._sms_failed = True
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
                return await self._finish(self._api, self._pending)

        if user_input is None and self._sms_failed and not errors:
            errors["base"] = "sms_failed"
        return self.async_show_form(
            step_id="mfa", data_schema=MFA_SCHEMA, errors=errors,
            description_placeholders={
                "account": self._pending.get(CONF_ACCOUNT, ""),
            },
        )
