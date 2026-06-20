"""Helpers for reading normalized config-entry values."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from .connection_helpers import normalize_host, validate_port
from .const import DEFAULT_PORT, DOMAIN


def merged_entry_data(entry: ConfigEntry) -> dict[str, Any]:
    """Return config-entry data merged with options (options override data)."""
    merged: dict[str, Any] = dict(entry.data)
    merged.update(entry.options)
    return merged


def entry_target(entry: ConfigEntry) -> tuple[str, int] | None:
    """Return normalized host/port from an existing config entry."""
    merged = merged_entry_data(entry)
    host_value = merged.get(CONF_HOST)
    if host_value is None:
        return None
    try:
        host = normalize_host(str(host_value))
        port = validate_port(merged.get(CONF_PORT, DEFAULT_PORT))
    except (TypeError, ValueError):
        return None
    return host, port


def is_target_used_by_other_entry(
    hass: HomeAssistant,
    host: str,
    port: int,
    *,
    exclude_entry_id: str | None = None,
) -> bool:
    """Return True when another config entry already uses host/port."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if exclude_entry_id is not None and entry.entry_id == exclude_entry_id:
            continue
        if entry_target(entry) == (host, port):
            return True
    return False
