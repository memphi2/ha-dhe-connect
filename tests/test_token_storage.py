"""Tests for DHE token storage backends."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

try:
    from tests.client_test_support import _load_component_module
except ModuleNotFoundError:
    from client_test_support import _load_component_module


class _FakeConfig:
    def __init__(self, base_path: Path) -> None:
        self._base_path = base_path

    def path(self, relative_path: str = "") -> str:
        return str((self._base_path / relative_path).resolve())


class _FakeConfigEntries:
    def __init__(self) -> None:
        self.update_calls: list[dict[str, object]] = []

    def async_update_entry(
        self,
        entry: SimpleNamespace,
        *,
        data: dict[str, object] | None = None,
    ) -> bool:
        if data is not None:
            entry.data = data
        self.update_calls.append({"entry": entry, "data": data})
        return True


class _FakeHass:
    def __init__(self, base_path: Path) -> None:
        self.data = {}
        self.config = _FakeConfig(base_path)
        self.config_entries = _FakeConfigEntries()

    async def async_add_executor_job(
        self,
        func: Callable[..., object],
        *args: object,
    ) -> object:
        return func(*args)


def _module():
    _load_component_module("const")
    return _load_component_module("token_storage")


async def test_config_entry_token_store_saves_and_clears_token(tmp_path) -> None:
    token_storage = _module()
    hass = _FakeHass(tmp_path)
    entry = SimpleNamespace(entry_id="entry-1", data={"host": "dhe.local"})
    store = token_storage.ConfigEntryTokenStore(hass, entry)

    await store.async_save_token("entry-token-value-000001")
    assert entry.data["token"] == "entry-token-value-000001"

    await store.async_clear_token()
    assert "token" not in entry.data


async def test_migration_retains_source_through_reload_until_next_ha_start(tmp_path) -> None:
    token_storage = _module()
    hass = _FakeHass(tmp_path)
    entry = SimpleNamespace(entry_id="entry-1", data={"host": "dhe.local"})
    legacy_file = Path(
        hass.config.path(".storage/stiebel_dhe_connect_token_dhe_8443.txt")
    )
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text("legacy-token-value-000001", encoding="utf-8")

    migrated = await token_storage.async_migrate_legacy_token_file(
        hass,
        entry,
        ".storage/stiebel_dhe_connect_token_dhe_8443.txt",
    )

    assert migrated is True
    assert entry.data["token"] == "legacy-token-value-000001"
    assert legacy_file.exists()
    assert entry.data[token_storage.CONF_LEGACY_TOKEN_FILES] == [legacy_file.name]
    assert not await token_storage.async_migrate_legacy_token_files(hass, entry, ())
    assert legacy_file.exists()

    restarted_hass = _FakeHass(tmp_path)
    assert not await token_storage.async_migrate_legacy_token_files(restarted_hass, entry, ())
    assert not legacy_file.exists()
    assert token_storage.CONF_LEGACY_TOKEN_FILES not in entry.data


async def test_existing_token_also_defers_legacy_deletion_until_restart(
    tmp_path,
) -> None:
    token_storage = _module()
    hass = _FakeHass(tmp_path)
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={"host": "dhe.local", "token": "entry-token-value-000001"},
    )
    legacy_file = Path(
        hass.config.path(".storage/stiebel_dhe_connect_token_dhe_8443.txt")
    )
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text("legacy-token-value-000001", encoding="utf-8")

    migrated = await token_storage.async_migrate_legacy_token_file(
        hass,
        entry,
        ".storage/stiebel_dhe_connect_token_dhe_8443.txt",
    )

    assert migrated is False
    assert entry.data["token"] == "entry-token-value-000001"
    assert legacy_file.exists()
    assert len(hass.config_entries.update_calls) == 1

    await token_storage.async_migrate_legacy_token_files(_FakeHass(tmp_path), entry, ())
    assert not legacy_file.exists()


@pytest.mark.parametrize("initial_token", [None, "malformed", "entry-token-value-000001"])
@pytest.mark.parametrize("paused_index", [0, 1])
async def test_migration_preserves_token_and_entry_updates_during_file_reads(
    tmp_path, initial_token, paused_index,
) -> None:
    module = _module()
    hass = _FakeHass(tmp_path)
    entry = SimpleNamespace(entry_id="entry-1", data={"host": "dhe.local", "name": "Before"})
    if initial_token is not None:
        entry.data["token"] = initial_token
    paths = [f".storage/stiebel_dhe_connect_token_{target}_8443.txt" for target in ("new", "old")]
    for index, path in enumerate(paths):
        await module.LegacyFileTokenStore(hass, path).async_save_token(
            f"legacy-token-value-{index:06d}"
        )
    reading, resume = asyncio.Event(), asyncio.Event()
    original_load = module.LegacyFileTokenStore.async_load_token

    async def paused_load(store):
        token = await original_load(store)
        if store.token_path == hass.config.path(paths[paused_index]):
            reading.set()
            await resume.wait()
        return token

    with patch.object(module.LegacyFileTokenStore, "async_load_token", paused_load):
        migration = asyncio.create_task(module.async_migrate_legacy_token_files(hass, entry, paths))
        try:
            await asyncio.wait_for(reading.wait(), timeout=5)
            await module.ConfigEntryTokenStore(hass, entry).async_save_token("fresh-token-value-000001")
            hass.config_entries.async_update_entry(entry, data={**entry.data, "name": "After"})
        finally:
            resume.set()
            migrated = await migration

    assert entry.data["token"] == "fresh-token-value-000001"
    assert entry.data["name"] == "After"
    assert migrated is False
    assert entry.data[module.CONF_LEGACY_TOKEN_FILES] == [Path(path).name for path in paths]
    assert all(Path(hass.config.path(path)).exists() for path in paths)


async def test_overlapping_migrations_preserve_current_token_and_pending_sources(tmp_path) -> None:
    module = _module()
    hass = _FakeHass(tmp_path)
    entry = SimpleNamespace(entry_id="entry-1", data={})
    paths = [f".storage/stiebel_dhe_connect_token_{target}_8443.txt" for target in ("first", "second")]
    for index, path in enumerate(paths):
        await module.LegacyFileTokenStore(hass, path).async_save_token(
            f"legacy-token-value-{index:06d}"
        )
    reading, resume = asyncio.Event(), asyncio.Event()
    original_load = module.LegacyFileTokenStore.async_load_token

    async def paused_load(store):
        token = await original_load(store)
        if store.token_path == hass.config.path(paths[0]):
            reading.set()
            await resume.wait()
        return token

    with patch.object(module.LegacyFileTokenStore, "async_load_token", paused_load):
        first = asyncio.create_task(module.async_migrate_legacy_token_file(hass, entry, paths[0]))
        try:
            await asyncio.wait_for(reading.wait(), timeout=5)
            assert await module.async_migrate_legacy_token_file(hass, entry, paths[1])
        finally:
            resume.set()
            migrated = await first

    assert entry.data["token"] == "legacy-token-value-000001"
    assert migrated is False
    assert set(entry.data[module.CONF_LEGACY_TOKEN_FILES]) == {Path(path).name for path in paths}
    assert not await module.async_migrate_legacy_token_files(hass, entry, ())
    assert all(Path(hass.config.path(path)).exists() for path in paths)
    assert not await module.async_migrate_legacy_token_files(_FakeHass(tmp_path), entry, ())
    assert all(not Path(hass.config.path(path)).exists() for path in paths)


async def test_migrate_legacy_token_file_ignores_malformed_token(tmp_path) -> None:
    token_storage = _module()
    hass = _FakeHass(tmp_path)
    entry = SimpleNamespace(entry_id="entry-1", data={"host": "dhe.local"})
    legacy_file = Path(
        hass.config.path(".storage/stiebel_dhe_connect_token_dhe_8443.txt")
    )
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text("bad token", encoding="utf-8")

    migrated = await token_storage.async_migrate_legacy_token_file(
        hass,
        entry,
        ".storage/stiebel_dhe_connect_token_dhe_8443.txt",
    )

    assert migrated is False
    assert "token" not in entry.data
    assert not legacy_file.exists()


async def test_failed_config_entry_update_retains_source(tmp_path) -> None:
    module = _module()
    hass = _FakeHass(tmp_path)
    entry = SimpleNamespace(entry_id="entry-1", data={})
    path = ".storage/stiebel_dhe_connect_token_dhe_8443.txt"
    source = module.LegacyFileTokenStore(hass, path)
    await source.async_save_token("legacy-token-value-000001")
    with (
        patch.object(hass.config_entries, "async_update_entry", side_effect=RuntimeError),
        pytest.raises(RuntimeError),
    ):
        await module.async_migrate_legacy_token_file(hass, entry, path)
    assert Path(source.token_path).exists()


async def test_crash_before_persistence_can_repeat_migration(tmp_path) -> None:
    module = _module()
    path = ".storage/stiebel_dhe_connect_token_dhe_8443.txt"
    hass = _FakeHass(tmp_path)
    source = module.LegacyFileTokenStore(hass, path)
    await source.async_save_token("legacy-token-value-000001")
    for restarted_hass in (hass, _FakeHass(tmp_path)):
        # Disk still contains the original entry, not the changed in-memory data.
        entry = SimpleNamespace(entry_id="entry-1", data={"host": "dhe.local"})
        assert await module.async_migrate_legacy_token_file(restarted_hass, entry, path)
        assert entry.data["token"] == "legacy-token-value-000001"
        assert Path(source.token_path).exists()


async def test_failed_cleanup_keeps_marker_for_retry(tmp_path) -> None:
    module = _module()
    hass = _FakeHass(tmp_path)
    path = ".storage/stiebel_dhe_connect_token_dhe_8443.txt"
    entry = SimpleNamespace(entry_id="entry-1", data={
        "token": "existing-token-value-0001",
        module.CONF_LEGACY_TOKEN_FILES: [Path(path).name],
    })
    await module.LegacyFileTokenStore(hass, path).async_save_token("legacy-token-value-000001")
    with (
        patch.object(module.os, "remove", side_effect=PermissionError),
        pytest.raises(PermissionError),
    ):
        await module.async_migrate_legacy_token_files(hass, entry, ())
    assert module.CONF_LEGACY_TOKEN_FILES in entry.data
    assert Path(hass.config.path(path)).exists()
    await module.async_migrate_legacy_token_files(hass, entry, ())
    assert module.CONF_LEGACY_TOKEN_FILES not in entry.data


async def test_pairing_clear_removes_pending_sources_and_cannot_reimport(tmp_path) -> None:
    module = _module()
    hass = _FakeHass(tmp_path)
    entry = SimpleNamespace(entry_id="entry-1", data={})
    path = ".storage/stiebel_dhe_connect_token_dhe_8443.txt"
    source = module.LegacyFileTokenStore(hass, path)
    await source.async_save_token("legacy-token-value-000001")
    await module.async_migrate_legacy_token_file(hass, entry, path)
    await module.ConfigEntryTokenStore(hass, entry).async_clear_token()
    assert not Path(source.token_path).exists()
    assert "token" not in entry.data
    assert module.CONF_LEGACY_TOKEN_FILES not in entry.data
    assert not await module.async_migrate_legacy_token_file(_FakeHass(tmp_path), entry, path)


async def test_token_change_after_restart_defers_pending_cleanup_again(tmp_path) -> None:
    module = _module()
    hass = _FakeHass(tmp_path)
    path = ".storage/stiebel_dhe_connect_token_dhe_8443.txt"
    entry = SimpleNamespace(entry_id="entry-1", data={
        "token": "existing-token-value-0001",
        module.CONF_LEGACY_TOKEN_FILES: [Path(path).name],
    })
    await module.LegacyFileTokenStore(hass, path).async_save_token("legacy-token-value-000001")
    await module.ConfigEntryTokenStore(hass, entry).async_save_token("new-entry-token-value-0001")
    await module.async_migrate_legacy_token_files(hass, entry, ())
    assert Path(hass.config.path(path)).exists()
    assert entry.data["token"] == "new-entry-token-value-0001"


def test_migration_marker_cannot_delete_unrelated_or_outside_files(tmp_path) -> None:
    module = _module()
    hass = _FakeHass(tmp_path)
    entry = SimpleNamespace(data={module.CONF_LEGACY_TOKEN_FILES: [
        "../stiebel_dhe_connect_token_outside.txt", "/tmp/stiebel_dhe_connect_token_bad.txt",
        "core.config_entries", "stiebel_dhe_connect_token_ok.txt", None,
    ]})
    assert module.legacy_token_paths(hass, entry) == (
        hass.config.path(".storage/stiebel_dhe_connect_token_ok.txt"),
    )
