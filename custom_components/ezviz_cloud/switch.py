"""Privacy mask switch."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import EzvizCloudApi
from .const import DOMAIN
from .coordinator import EzvizCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EzvizPrivacySwitch(data["coordinator"], data["api"])])


class EzvizPrivacySwitch(CoordinatorEntity[EzvizCoordinator], SwitchEntity):
    _attr_has_entity_name = True
    _attr_name = "镜头遮蔽"
    _attr_icon = "mdi:cctv-off"

    def __init__(self, coordinator: EzvizCoordinator, api: EzvizCloudApi) -> None:
        super().__init__(coordinator)
        self._api = api
        self._optimistic: bool | None = None
        self._attr_unique_id = f"{api.serial}_privacy"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, api.serial)},
            "name": f"EZVIZ {api.serial}",
            "manufacturer": "EZVIZ",
            "model": "C6CN",
        }

    @property
    def is_on(self) -> bool | None:
        if self._optimistic is not None:
            return self._optimistic
        return (self.coordinator.data or {}).get("privacy")

    async def _set(self, enable: bool) -> None:
        # 云端回显有几秒延迟，先乐观置位，再等一会儿校准
        self._optimistic = enable
        self.async_write_ha_state()
        try:
            await self.hass.async_add_executor_job(self._api.set_privacy, enable)
            await asyncio.sleep(6)
        finally:
            self._optimistic = None
            await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(False)
