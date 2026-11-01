"""Select the supported Home Assistant API generation."""

from homeassistant.const import MAJOR_VERSION, MINOR_VERSION

HA_2026_11 = (MAJOR_VERSION, MINOR_VERSION) >= (2026, 11)
