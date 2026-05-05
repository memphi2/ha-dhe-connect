"""Constants for Stiebel DHE Connect."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "stiebel_dhe_connect"

DEFAULT_NAME = "DHE Connect"
DEFAULT_PORT = 8443
DEFAULT_POLL_INTERVAL = 600

CONF_POLL_INTERVAL = "poll_interval"
# Backward compatibility for entries created by v0.2/v0.3.
CONF_PING_INTERVAL = "ping_interval"

PLATFORMS = [Platform.CLIMATE, Platform.SENSOR]
