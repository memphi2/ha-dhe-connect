"""Helpers for reading merged config-entry values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry


def merged_entry_data(entry: ConfigEntry) -> Mapping[str, Any]:
    """Return config-entry data merged with options (options override data)."""
    merged: dict[str, Any] = dict(entry.data)
    merged.update(entry.options)
    return merged
