"""PTZ direction buttons."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import EzvizCloudApi
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DIRS = {
    "up": ("上", "mdi:arrow-up-bold"),
    "down": ("下", "mdi:arrow-down-bold"),
    "left": ("左", "mdi:arrow-left-bold"),
    "right": ("右", "mdi:arrow-right-bold"),
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            EzvizPtzButton(data["api"], data["settings"], d, label, icon)
            for d, (label, icon) in DIRS.items()
        ]
    )


class EzvizPtzButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, api: EzvizCloudApi, settings, direction: str, label: str, icon: str) -> None:
        self._api = api
        self._settings = settings
        self._direction = direction
        self._attr_name = f"云台 {label}"
        self._attr_icon = icon
        self._attr_unique_id = f"{api.serial}_ptz_{direction}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, api.serial)},
            "name": f"EZVIZ {api.serial}",
        }

    async def async_press(self) -> None:
        await self.hass.async_add_executor_job(
            self._api.ptz,
            self._direction,
            self._settings.ms,
            self._settings.speed,
        )
