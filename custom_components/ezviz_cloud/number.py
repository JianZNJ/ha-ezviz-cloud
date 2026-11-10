"""PTZ duration / speed numbers."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import EzvizCloudApi
from .const import DOMAIN, DEFAULT_PTZ_MS, DEFAULT_PTZ_SPEED

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    settings = data["settings"]
    await settings.async_load()
    async_add_entities(
        [
            EzvizSettingNumber(
                data["api"], settings, "ms", "云台时长", "mdi:timer-outline",
                50, 5000, 50, DEFAULT_PTZ_MS, "ms",
            ),
            EzvizSettingNumber(
                data["api"], settings, "speed", "云台速度", "mdi:speedometer",
                1, 10, 1, DEFAULT_PTZ_SPEED, "",
            ),
        ]
    )


class EzvizSettingNumber(NumberEntity):
    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        api: EzvizCloudApi,
        settings,
        key: str,
        name: str,
        icon: str,
        min_v: float,
        max_v: float,
        step: float,
        default: float,
        unit: str,
    ) -> None:
        self._api = api
        self._settings = settings
        self._key = key
        self._unit = unit
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{api.serial}_{key}"
        self._attr_native_min_value = min_v
        self._attr_native_max_value = max_v
        self._attr_native_step = step
        self._attr_native_value = getattr(settings, key, default)
        self._attr_native_unit_of_measurement = unit or None
        self._attr_device_info = {
            "identifiers": {(DOMAIN, api.serial)},
            "name": f"EZVIZ {api.serial}",
        }

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        setattr(self._settings, self._key, int(value))
        await self._settings.async_save()
        self.async_write_ha_state()
