"""Token storage backends for DHE pairing tokens."""

from __future__ import annotations

import contextlib
import logging
import os
import stat
from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_TOKEN, DOMAIN
from .token_file_helpers import TOKEN_FILE_PREFIX, TOKEN_FILE_SUFFIX

_LOGGER = logging.getLogger(__name__)
CONF_LEGACY_TOKEN_FILES = "legacy_token_files"
_PENDING_MIGRATIONS = f"{DOMAIN}_pending_token_migrations"


def legacy_token_paths(hass: HomeAssistant, entry: ConfigEntry) -> tuple[str, ...]:
    """Return migration source paths, restricted to legacy storage filenames."""
    names = entry.data.get(CONF_LEGACY_TOKEN_FILES, [])
    if not isinstance(names, list):
        return ()
    return tuple(
        hass.config.path(os.path.join(".storage", name))
        for name in names
        if isinstance(name, str)
        and os.path.basename(name) == name
        and name.startswith(TOKEN_FILE_PREFIX)
        and name.endswith(TOKEN_FILE_SUFFIX)
    )


def _defer_migration_cleanup(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """A token changed in this process has not yet survived a HA restart."""
    hass.data.setdefault(_PENDING_MIGRATIONS, set()).add(entry.entry_id)


@runtime_checkable
class DHETokenStore(Protocol):
    """Persistence surface used by the DHE client."""

    async def async_load_token(self) -> str:
        """Return the stored token, or an empty string when none exists."""

    async def async_save_token(self, token: str) -> None:
        """Persist a token."""

    async def async_clear_token(self) -> None:
        """Remove the stored token."""


def token_is_well_formed(token: str) -> bool:
    """Return whether a stored DHE token has the expected local shape."""
    return bool(token) and len(token) >= 20 and not any(ch.isspace() for ch in token)


def _entry_token(entry: ConfigEntry) -> str:
    """Return the raw token value from config-entry data."""
    value = dict(getattr(entry, "data", {}) or {}).get(CONF_TOKEN, "")
    return str(value or "").strip()


class InMemoryTokenStore:
    """Non-persistent token storage for one-shot setup validation."""

    def __init__(self, token: str = "") -> None:
        self.token = token.strip()

    async def async_load_token(self) -> str:
        """Return the in-memory token."""
        return self.token

    async def async_save_token(self, token: str) -> None:
        """Save the token in memory."""
        self.token = token.strip()

    async def async_clear_token(self) -> None:
        """Clear the in-memory token."""
        self.token = ""


class LegacyFileTokenStore:
    """Legacy token-file storage used for migration and compatibility tests."""

    def __init__(self, hass: HomeAssistant, token_file: str) -> None:
        self.hass = hass
        self.token_path = (
            token_file if os.path.isabs(token_file) else hass.config.path(token_file)
        )

    async def async_load_token(self) -> str:
        """Read the legacy token file."""

        def _read() -> str:
            if not os.path.exists(self.token_path):
                return ""
            with open(self.token_path, encoding="utf-8") as file:
                return file.read().strip()

        return str(await self.hass.async_add_executor_job(_read))

    async def async_save_token(self, token: str) -> None:
        """Write the legacy token file with owner-only permissions."""

        def _write() -> None:
            token_dir = os.path.dirname(self.token_path)
            os.makedirs(token_dir, exist_ok=True)
            tmp_path = f"{self.token_path}.tmp"
            file_descriptor = os.open(
                tmp_path,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                stat.S_IRUSR | stat.S_IWUSR,
            )
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as file:
                file.write(token)
            with contextlib.suppress(OSError):
                os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(tmp_path, self.token_path)

        await self.hass.async_add_executor_job(_write)

    async def async_clear_token(self) -> None:
        """Delete the legacy token file."""

        def _delete() -> None:
            with contextlib.suppress(FileNotFoundError):
                os.remove(self.token_path)

        await self.hass.async_add_executor_job(_delete)


class ConfigEntryTokenStore:
    """Persist the DHE token inside config-entry data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry

    async def async_load_token(self) -> str:
        """Return the token stored in the config entry."""
        return _entry_token(self.entry)

    async def async_save_token(self, token: str) -> None:
        """Persist the token in the config entry."""
        _async_update_entry_token(self.hass, self.entry, token.strip())

    async def async_clear_token(self) -> None:
        """Remove the token from the config entry."""
        for path in legacy_token_paths(self.hass, self.entry):
            await LegacyFileTokenStore(self.hass, path).async_clear_token()
        _async_update_entry_token(self.hass, self.entry, "")


def _async_update_entry_token(
    hass: HomeAssistant,
    entry: ConfigEntry,
    token: str,
) -> bool:
    """Update only the token field in config-entry data."""
    data = dict(getattr(entry, "data", {}) or {})
    if token:
        data[CONF_TOKEN] = token
        if CONF_LEGACY_TOKEN_FILES in data:
            _defer_migration_cleanup(hass, entry)
    else:
        data.pop(CONF_TOKEN, None)
        data.pop(CONF_LEGACY_TOKEN_FILES, None)
        hass.data.get(_PENDING_MIGRATIONS, set()).discard(entry.entry_id)
    if data == dict(getattr(entry, "data", {}) or {}):
        return False
    return bool(hass.config_entries.async_update_entry(entry, data=data))


async def async_migrate_legacy_token_file(
    hass: HomeAssistant,
    entry: ConfigEntry,
    token_file: str,
) -> bool:
    """Import one legacy token, retaining its source until a later HA start."""
    return await async_migrate_legacy_token_files(hass, entry, (token_file,))


async def async_migrate_legacy_token_files(
    hass: HomeAssistant,
    entry: ConfigEntry,
    token_files: Iterable[str],
) -> bool:
    """Import tokens and remove sources only after a persisted migration reload."""
    pending_paths = legacy_token_paths(hass, entry)
    stores = _legacy_file_stores(hass, (*token_files, *pending_paths))
    if not stores:
        return False

    has_entry_token = token_is_well_formed(_entry_token(entry))
    if (
        has_entry_token
        and pending_paths
        and entry.entry_id not in hass.data.get(_PENDING_MIGRATIONS, set())
    ):
        # This marker and token were loaded from disk, not set by this process.
        for store in stores:
            await store.async_clear_token()
        data = dict(entry.data)
        data.pop(CONF_LEGACY_TOKEN_FILES, None)
        hass.config_entries.async_update_entry(entry, data=data)
        return False

    migrated = False
    data = dict(entry.data)
    retained_names: list[str] = []
    for store in stores:
        token = await store.async_load_token()
        if not token_is_well_formed(token):
            if token:
                _LOGGER.warning(
                    "Ignoring malformed legacy DHE token while migrating entry=%s",
                    getattr(entry, "entry_id", "unknown"),
                )
            await store.async_clear_token()
            continue
        retained_names.append(os.path.basename(store.token_path))
        if not has_entry_token:
            data[CONF_TOKEN] = token
            has_entry_token = True
            migrated = True
    if retained_names:
        data[CONF_LEGACY_TOKEN_FILES] = retained_names
        _defer_migration_cleanup(hass, entry)
        if data != dict(entry.data):
            hass.config_entries.async_update_entry(entry, data=data)
    return migrated


def _legacy_file_stores(
    hass: HomeAssistant,
    token_files: Iterable[str],
) -> tuple[LegacyFileTokenStore, ...]:
    """Return de-duplicated legacy token stores."""
    stores: list[LegacyFileTokenStore] = []
    seen_paths: set[str] = set()
    for token_file in token_files:
        store = LegacyFileTokenStore(hass, token_file)
        path = os.path.normcase(os.path.abspath(store.token_path))
        if path in seen_paths:
            continue
        seen_paths.add(path)
        stores.append(store)
    return tuple(stores)
