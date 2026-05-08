"""Constants for Stiebel DHE Connect."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "stiebel_dhe_connect"

DEFAULT_NAME = "DHE Connect"
DEFAULT_PORT = 8443
CONF_WATER_DASHBOARD_COMPATIBLE = "water_dashboard_compatible"
DEFAULT_WATER_DASHBOARD_COMPATIBLE = False

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.BUTTON,
]
