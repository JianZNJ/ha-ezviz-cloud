"""EZVIZ Cloud (CN) — 镜头遮蔽开关 + 云台方向控制。"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_validation as cv

from .api import (
    EzvizCloudApi,
    EzvizCloudAuthError,
    EzvizCloudError,
    EzvizCloudReauthRequired,
)
from .const import (
    CONF_ACCOUNT,
    CONF_PASSWORD,
    CONF_SERIAL,
    CONF_TOKEN,
    DEFAULT_PTZ_MS,
    DEFAULT_PTZ_SPEED,
    DOMAIN,
    PTZ_DIRECTIONS,
)
from .coordinator import EzvizCoordinator
from .settings import PtzSettings

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.NUMBER, Platform.SWITCH, Platform.BUTTON]

SERVICE_PTZ = "ptz"
SERVICE_PTZ_SCHEMA = vol.Schema(
    {
        vol.Optional("serial"): cv.string,
        vol.Required("direction"): vol.In(PTZ_DIRECTIONS),
        vol.Optional("ms", default=DEFAULT_PTZ_MS): vol.All(
            vol.Coerce(int), vol.Range(min=50, max=5000)
        ),
        vol.Optional("speed", default=DEFAULT_PTZ_SPEED): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=10)
        ),
    }
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the ptz service once."""
    hass.data.setdefault(DOMAIN, {})

    async def _handle_ptz(call: ServiceCall) -> None:
        entries = hass.data.get(DOMAIN, {})
        if not entries:
            raise EzvizCloudError("没有已配置的 EZVIZ 实例")
        serial = call.data.get("serial")
        target = None
        for data in entries.values():
            api: EzvizCloudApi = data["api"]
            if serial is None or api.serial == serial:
                target = api
                break
        if target is None:
            raise EzvizCloudError(f"找不到序列号 {serial}")

        await hass.async_add_executor_job(
            target.ptz,
            call.data["direction"],
            call.data["ms"],
            call.data["speed"],
        )

    hass.services.async_register(
        DOMAIN, SERVICE_PTZ, _handle_ptz, schema=SERVICE_PTZ_SCHEMA
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api = EzvizCloudApi(
        account=entry.data[CONF_ACCOUNT],
        password=entry.data[CONF_PASSWORD],
        serial=entry.data[CONF_SERIAL],
        token=entry.data.get(CONF_TOKEN),
    )

    try:
        await hass.async_add_executor_job(api.ensure_login)
    except EzvizCloudReauthRequired as err:
        # 交给 HA 触发 reauth 流程，用户填一次短信验证码即可；绝不后台自动发短信。
        raise ConfigEntryAuthFailed(str(err)) from err
    except (EzvizCloudAuthError, EzvizCloudError) as err:
        _LOGGER.error("EZVIZ 会话不可用: %s", err)
        return False

    await _store_token(hass, entry, api)

    coordinator = EzvizCoordinator(hass, api)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
        "settings": PtzSettings(hass),
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _store_token(hass: HomeAssistant, entry: ConfigEntry, api: EzvizCloudApi) -> None:
    token = api.token
    if token and token != entry.data.get(CONF_TOKEN):
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_TOKEN: token}
        )


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok
