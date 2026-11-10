"""Small mutable holder for PTZ defaults (shared by button/number)."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DEFAULT_PTZ_MS, DEFAULT_PTZ_SPEED

STORAGE_KEY = "ezviz_cloud.ptz_settings"
STORAGE_VERSION = 1


class PtzSettings:
    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store[dict](hass, STORAGE_VERSION, STORAGE_KEY)
        self.ms: int = DEFAULT_PTZ_MS
        self.speed: int = DEFAULT_PTZ_SPEED

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if isinstance(data, dict):
            self.ms = int(data.get("ms", DEFAULT_PTZ_MS))
            self.speed = int(data.get("speed", DEFAULT_PTZ_SPEED))

    async def async_save(self) -> None:
        await self._store.async_save({"ms": self.ms, "speed": self.speed})
