"""Coordinator polling the cloud switch state."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import notify
from .api import EzvizCloudApi, EzvizCloudAuthError, EzvizCloudError
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

# 连续失败多少次才发持久通知：30s 一轮，3 次≈90s，避开偶发抖动。
NOTIFY_AFTER_FAILURES = 3


class EzvizCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, api: EzvizCloudApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}-{api.serial}",
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )
        self.api = api
        self._failures = 0

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.hass.async_add_executor_job(self.api.status)
        except EzvizCloudAuthError as err:
            # 认证问题不要让 coordinator 每 30s 重试：密码登录会触发短信轰炸。
            # ConfigEntryAuthFailed 会让 HA 自动创建 repair（需要重新认证）。
            raise ConfigEntryAuthFailed(str(err)) from err
        except EzvizCloudError as err:
            self._failures += 1
            if self._failures == NOTIFY_AFTER_FAILURES:
                notify.async_notify(
                    self.hass,
                    self.api.serial,
                    (
                        f"已连续 {self._failures} 次拉取失败，实体当前不可用：\n\n"
                        f"`{err}`\n\n"
                        "常见原因：萤石 /v3/apigateway/login 续期接口故障、会话过期、"
                        "或账号短信配额用尽。\n"
                        "恢复方式：运行 ezviz_local/relogin.py，或重启集成 "
                        "ezviz_cloud。恢复后本通知会自动消失。"
                    ),
                )
            raise UpdateFailed(str(err)) from err
        if self._failures:
            self._failures = 0
            notify.async_dismiss(self.hass, self.api.serial)
        return data
