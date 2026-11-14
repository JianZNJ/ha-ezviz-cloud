"""EZVIZ Cloud (CN) — 镜头遮蔽开关 + 云台方向控制。"""

from __future__ import annotations

import logging
from typing import Any

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
from . import notify
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
    _dbg_tok = entry.data.get(CONF_TOKEN) or {}
    api = EzvizCloudApi(
        account=entry.data[CONF_ACCOUNT],
        password=entry.data[CONF_PASSWORD],
        serial=entry.data[CONF_SERIAL],
        token=entry.data.get(CONF_TOKEN),
        # 续期接口 500 时用受限密码登录兜底；默认开，可在集成选项里关掉。
        allow_password_login=bool(entry.options.get("auto_relogin", True)),
    )

    # 云端续期会轮换 rf_session_id：把新 token 写回条目，避免重启后拿旧
    # refreshSessionId 续期（萤石对该情况直接返回 500）。
    def _persist_token(tok: dict[str, Any]) -> None:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_TOKEN: tok}
        )

    def _on_token_update(tok: dict[str, Any]) -> None:
        hass.loop.call_soon_threadsafe(_persist_token, tok)

    api.on_token_update = _on_token_update

    try:
        await hass.async_add_executor_job(api.ensure_login)
    except EzvizCloudReauthRequired as err:
        # 交给 HA 触发 reauth 流程；绝不后台自动发短信。
        notify.async_notify(
            hass,
            entry.entry_id,
            (
                "保存的会话已不可用且无法续期，需要重新认证。\n\n"
                f"`{err}`\n\n"
                "运行 `ezviz_local/relogin.py` 可自动完成（密码登录换 token），"
                "或到「设置 → 设备与服务」点该集成的「重新认证」。"
            ),
        )
        raise ConfigEntryAuthFailed(str(err)) from err
    except (EzvizCloudAuthError, EzvizCloudError) as err:
        _LOGGER.error("EZVIZ 会话不可用: %s", err)
        notify.async_notify(
            hass,
            entry.entry_id,
            f"集成启动失败：\n\n`{err}`\n\nHA 会自动重试；恢复后本通知会消失。",
        )
        return False

    await _store_token(hass, entry, api)

    coordinator = EzvizCoordinator(hass, api)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed as err:
        notify.async_notify(
            hass,
            entry.entry_id,
            (
                "会话已失效且无法续期，HA 已创建「重新认证」修复项，但侧边栏不会弹提示。\n\n"
                f"`{err}`\n\n"
                "恢复：运行 `ezviz_local/relogin.py`（密码登录换 token 后自动提交），"
                "或到「设置 → 设备与服务」点该集成「重新认证」。"
            ),
        )
        raise
    except Exception as err:  # noqa: BLE001
        notify.async_notify(
            hass,
            entry.entry_id,
            f"首次拉取失败：\n\n`{err}`\n\nHA 会自动重试；恢复后本通知会消失。",
        )
        raise
    notify.async_dismiss(hass, entry.entry_id)
    notify.async_dismiss(hass, api.serial)

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
