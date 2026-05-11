"""Helpers for runtime access from platform setup functions."""

from __future__ import annotations

from typing import Protocol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .client import DHEClient
from .const import DOMAIN


class RuntimeDataProtocol(Protocol):
    """Protocol for runtime data stored in hass.data."""

    client: DHEClient
    name: str


def get_runtime_data(hass: HomeAssistant, entry: ConfigEntry) -> RuntimeDataProtocol:
    """Return integration runtime data for a config entry."""
    return hass.data[DOMAIN][entry.entry_id]
