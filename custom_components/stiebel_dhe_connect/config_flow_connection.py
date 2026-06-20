"""Shared connection helpers for config and options flow paths."""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Mapping
from typing import Any

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from .config_entry_helpers import entry_target as _entry_target
from .connection_helpers import target_changed
from .const import DEFAULT_PORT
from .pairing_validation import _abs_config_path as _validation_abs_config_path
from .token_file_helpers import token_file_for_target

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
    """Copy the existing DHE token when a configured device target changes."""
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

    old_path = _validation_abs_config_path(hass, token_file_for_target(old_host, old_port))
    new_path = _validation_abs_config_path(hass, token_file_for_target(new_host, new_port))
    if old_path == new_path:
        return False

    def _copy() -> bool:
        if not os.path.exists(old_path) or os.path.exists(new_path):
            return False
        entry_id = str(getattr(entry, "entry_id", "unknown"))
        try:
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            shutil.copy2(old_path, new_path)
        except OSError as err:
            _LOGGER.debug(
                "Could not preserve DHE token while retargeting entry=%s: %s",
                entry_id,
                err,
            )
            return False
        return True

    return bool(await hass.async_add_executor_job(_copy))
