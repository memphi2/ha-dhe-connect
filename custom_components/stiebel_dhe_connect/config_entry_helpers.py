"""Helpers for reading merged config-entry values."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry


def merged_entry_data(entry: ConfigEntry) -> dict[str, Any]:
    """Return config-entry data merged with options (options override data)."""
    merged: dict[str, Any] = dict(entry.data)
    merged.update(entry.options)
    return merged
