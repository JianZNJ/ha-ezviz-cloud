"""Persistent notifications for EZVIZ Cloud health issues.

HA 只在 ConfigEntryAuthFailed 时自动建 repair（需要重新认证）；普通的
UpdateFailed / setup_retry 只会进日志，侧边栏不会有任何提示。这里补一条
持久通知，让「云接口挂了但没人看见」变成可见事件，恢复后自动撤掉。
"""

from __future__ import annotations

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant

TITLE = "EZVIZ 云连接异常"


def _notification_id(key: str) -> str:
    return f"ezviz_cloud_health_{key}"


def async_notify(hass: HomeAssistant, key: str, message: str) -> None:
    """创建/更新一条持久通知（同一 key 只占一条）。"""
    persistent_notification.async_create(
        hass, message, title=TITLE, notification_id=_notification_id(key)
    )


def async_dismiss(hass: HomeAssistant, key: str) -> None:
    """恢复后撤掉通知。"""
    persistent_notification.async_dismiss(hass, _notification_id(key))
