"""Const for the EZVIZ Cloud (CN) integration."""

DOMAIN = "ezviz_cloud"
NAME = "EZVIZ Cloud (CN)"

API_HOST = "api.ys7.com"

CONF_ACCOUNT = "account"
CONF_PASSWORD = "password"
CONF_SERIAL = "serial"
CONF_TOKEN = "token"

PRIVACY_SWITCH_TYPE = 7
PRIVACY_CHANNEL = 0  # 实测：enable=1 只在 channel 0 生效
SCAN_INTERVAL = 30

DEFAULT_PTZ_MS = 300
DEFAULT_PTZ_SPEED = 5
PTZ_DIRECTIONS = ("up", "down", "left", "right")
