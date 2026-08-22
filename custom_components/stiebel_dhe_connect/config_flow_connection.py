"""Shared connection helpers for config and options flow paths."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from .config_entry_helpers import entry_target as _entry_target
from .connection_helpers import target_changed
from .const import DEFAULT_PORT
from .token_file_helpers import token_file_for_target
from .token_storage import async_migrate_legacy_token_files

_LOGGER = logging.getLogger(__name__)


def connection_options_for_entry(
    entry: config_entries.ConfigEntry,
    connection_data: Mapping[str, Any],
) -> dict[str, Any]:
    """Return options updated with normalized connection fields."""
    options = dict(entry.options)
    options.update(connection_data)
    return options


async def async_preserve_token_for_retarget(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    connection_data: Mapping[str, Any],
) -> bool:
    """Migrate legacy DHE token files before a configured target changes."""
    current_target = _entry_target(entry)
    if current_target is None:
        return False
    old_host, old_port = current_target
    new_host = str(connection_data[CONF_HOST])
    new_port = int(connection_data[CONF_PORT])
    if not target_changed(
        {CONF_HOST: old_host, CONF_PORT: old_port},
        new_host,
        new_port,
        default_port=DEFAULT_PORT,
    ):
        return False

    migrated = await async_migrate_legacy_token_files(
        hass,
        entry,
        (
            token_file_for_target(new_host, new_port),
            token_file_for_target(old_host, old_port),
        ),
    )
    if not migrated:
        _LOGGER.debug(
            "No legacy DHE token file needed migration while retargeting entry=%s",
            getattr(entry, "entry_id", "unknown"),
        )
    return migrated
