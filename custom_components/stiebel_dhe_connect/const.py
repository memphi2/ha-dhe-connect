"""Constants for Stiebel DHE Connect."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "stiebel_dhe_connect"

DEFAULT_NAME = "DHE Connect"
DEFAULT_PORT = 8443

PLATFORMS = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.BUTTON,
]
