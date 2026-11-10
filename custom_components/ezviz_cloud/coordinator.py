"""Coordinator polling the cloud switch state."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import EzvizCloudApi, EzvizCloudError
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class EzvizCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, api: EzvizCloudApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}-{api.serial}",
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.hass.async_add_executor_job(self.api.status)
        except EzvizCloudError as err:
            raise UpdateFailed(str(err)) from err
