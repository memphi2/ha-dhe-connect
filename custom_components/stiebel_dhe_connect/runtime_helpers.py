"""Helpers for runtime access from config entries."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .client import DHEClient
from .const import DOMAIN


class RuntimeDataProtocol(Protocol):
    """Protocol for runtime data stored on a config entry."""

    client: DHEClient
    name: str


def set_runtime_data(entry: ConfigEntry, runtime: RuntimeDataProtocol) -> None:
    """Store integration runtime data on the config entry."""
    entry.runtime_data = runtime


def clear_runtime_data(entry: ConfigEntry) -> None:
    """Clear integration runtime data from a config entry."""
    entry.runtime_data = None


def get_runtime_data(hass: HomeAssistant, entry: ConfigEntry) -> RuntimeDataProtocol:
    """Return integration runtime data for a config entry."""
    del hass
    runtime = cast(RuntimeDataProtocol | None, getattr(entry, "runtime_data", None))
    if runtime is None:
        raise RuntimeError("DHE Connect runtime data is not loaded")
    return runtime


def iter_loaded_runtime_data(
    hass: HomeAssistant,
) -> Iterator[tuple[str, RuntimeDataProtocol]]:
    """Yield loaded integration runtime data keyed by config entry id."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        runtime = cast(RuntimeDataProtocol | None, getattr(entry, "runtime_data", None))
        if runtime is not None:
            yield entry.entry_id, runtime
