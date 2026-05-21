"""Helpers for connectivity checks and setup pairing validation."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Sequence

from homeassistant.core import HomeAssistant


from .client import DHEClient
from .client_types import DHEError
from .config_entry_helpers import entry_target
from .config_flow_discovery import SetupPairingResult, device_unique_id_from_info
from .connection_probe import async_can_connect as _async_can_connect
from .const import DOMAIN
from .pairing_helpers import map_pairing_error
from .token_file_helpers import (
    LEGACY_TOKEN_FILE,
    legacy_token_file_for_entry,
    legacy_token_files_for_target,
    stale_unconfigured_token_paths,
    token_file_for_target,
)

SETUP_PAIRING_TIMEOUT_SECONDS = 180.0


def _validation_path_getter(hass: HomeAssistant, path: str) -> str:
    """Return a normalized path with minimal test compatibility."""
    config = getattr(hass, "config", None)
    if config is None or not hasattr(config, "path"):
        return os.path.normcase(os.path.abspath(path))
    return os.path.normcase(os.path.abspath(config.path(path)))


def _abs_config_path(hass: HomeAssistant, path: str) -> str:
    """Return a normalized absolute Home Assistant config path."""
    return _validation_path_getter(hass, path)


def _configured_token_paths(hass: HomeAssistant) -> set[str]:
    """Return token paths that belong to currently configured DHE entries."""
    entries = getattr(getattr(hass, "config_entries", None), "async_entries", None)
    if entries is None:
        return set()

    paths: set[str] = set()
    for entry in entries(DOMAIN):
        paths.add(_abs_config_path(hass, legacy_token_file_for_entry(entry.entry_id)))
        target = entry_target(entry)
        if target is None:
            continue
        entry_host, entry_port = target
        paths.add(_abs_config_path(hass, token_file_for_target(entry_host, entry_port)))
        for legacy_path in legacy_token_files_for_target(entry_host, entry_port):
            paths.add(_abs_config_path(hass, legacy_path))
    return paths


def _setup_token_cleanup_context(
    hass: HomeAssistant,
    host: str,
    port: int,
    token_file: str,
) -> tuple[set[str], str, set[str]]:
    """Return token cleanup data without touching the filesystem."""
    explicit_paths = {
        _abs_config_path(hass, token_file),
        _abs_config_path(hass, LEGACY_TOKEN_FILE),
    }
    explicit_paths.update(
        _abs_config_path(hass, legacy_path)
        for legacy_path in legacy_token_files_for_target(host, port)
    )

    configured_paths = _configured_token_paths(hass)
    storage_path = hass.config.path(".storage")
    return explicit_paths, storage_path, configured_paths


async def _async_clear_setup_token_files(
    hass: HomeAssistant,
    host: str,
    port: int,
    token_file: str,
) -> None:
    """Remove stale setup tokens before requesting a fresh DHE pairing token."""
    explicit_paths, storage_path, configured_paths = _setup_token_cleanup_context(
        hass,
        host,
        port,
        token_file,
    )

    def _delete() -> list[str]:
        paths = set(explicit_paths)
        token_file_names: Sequence[str]
        try:
            token_file_names = os.listdir(storage_path)
        except OSError:
            token_file_names = ()
        paths.update(
            stale_unconfigured_token_paths(
                storage_path,
                token_file_names,
                configured_paths,
            )
        )
        removed: list[str] = []
        for path in paths:
            try:
                os.remove(path)
            except FileNotFoundError:
                continue
            except OSError:
                continue
            removed.append(path)
        return removed

    await hass.async_add_executor_job(_delete)


async def can_connect(hass: HomeAssistant, host: str, port: int) -> bool:
    """Check if the DHE web endpoint is reachable before setup/repair."""
    return await _async_can_connect(hass, host, port)


async def validate_setup_pairing(
    hass: HomeAssistant,
    host: str,
    port: int,
    token_file: str,
    *,
    client_factory: Callable[..., DHEClient] = DHEClient,
    error_mapper: Callable[[Exception, str], str] = map_pairing_error,
    clear_setup_token_files: Callable[[HomeAssistant, str, int, str], Awaitable[None]]
    = _async_clear_setup_token_files,
) -> SetupPairingResult:
    """Run one-shot pairing/auth validation for a setup or repair target."""
    await clear_setup_token_files(hass, host, port, token_file)
    probe_client = client_factory(
        hass=hass,
        host=host,
        port=port,
        token_file=token_file,
        name="Home Assistant",
    )
    try:
        await probe_client.validate_setup_authentication(
            timeout_seconds=SETUP_PAIRING_TIMEOUT_SECONDS
        )
    except asyncio.CancelledError:
        raise
    except (DHEError, TimeoutError, OSError, RuntimeError) as err:
        pairing_state = str(probe_client.diagnostic_state.get("pairing_state") or "")
        return SetupPairingResult(error_key=error_mapper(err, pairing_state))

    device_info = getattr(probe_client, "last_device_info", {})
    return SetupPairingResult(
        unique_id=device_unique_id_from_info(device_info)
        if isinstance(device_info, dict)
        else None
    )
