"""Tests for DHE token storage backends."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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


@pytest.mark.parametrize("save_fresh_token", [False, True])
async def test_pairing_reset_invalidates_an_inflight_legacy_read(tmp_path, save_fresh_token) -> None:
    module = _module()
    hass = _FakeHass(tmp_path)
    entry = SimpleNamespace(entry_id="entry-1", data={})
    path = ".storage/stiebel_dhe_connect_token_dhe_8443.txt"
    source = module.LegacyFileTokenStore(hass, path)
    await source.async_save_token("legacy-token-value-000001")
    await module.async_migrate_legacy_token_file(hass, entry, path)
    reading, resume = asyncio.Event(), asyncio.Event()
    original_load = module.LegacyFileTokenStore.async_load_token

    async def paused_load(store):
        token = await original_load(store)
        reading.set()
        await resume.wait()
        return token

    with patch.object(module.LegacyFileTokenStore, "async_load_token", paused_load):
        migration = asyncio.create_task(module.async_migrate_legacy_token_file(hass, entry, path))
        try:
            await asyncio.wait_for(reading.wait(), timeout=5)
            await module.ConfigEntryTokenStore(hass, entry).async_clear_token()
            assert "token" not in entry.data
            if save_fresh_token:
                await module.ConfigEntryTokenStore(hass, entry).async_save_token("fresh-token-value-000001")
        finally:
            resume.set()
            migrated = await migration

    assert module.CONF_LEGACY_TOKEN_FILES not in entry.data
    assert entry.data.get("token") == ("fresh-token-value-000001" if save_fresh_token else None)
    assert migrated is False
    assert not Path(source.token_path).exists()
    assert not await module.async_migrate_legacy_token_file(_FakeHass(tmp_path), entry, path)


async def test_migration_does_not_read_sources_during_pairing_reset(tmp_path) -> None:
    module = _module()
    hass = _FakeHass(tmp_path)
    entry = SimpleNamespace(entry_id="entry-1", data={})
    path = ".storage/stiebel_dhe_connect_token_dhe_8443.txt"
    await module.LegacyFileTokenStore(hass, path).async_save_token("legacy-token-value-000001")
    await module.async_migrate_legacy_token_file(hass, entry, path)
    deleting, resume = asyncio.Event(), asyncio.Event()
    original_clear = module.LegacyFileTokenStore.async_clear_token

    async def paused_clear(store):
        deleting.set()
        await resume.wait()
        await original_clear(store)

    with patch.object(module.LegacyFileTokenStore, "async_clear_token", paused_clear):
        reset = asyncio.create_task(module.ConfigEntryTokenStore(hass, entry).async_clear_token())
        try:
            await asyncio.wait_for(deleting.wait(), timeout=5)
            with patch.object(module.LegacyFileTokenStore, "async_load_token", side_effect=AssertionError("read during reset")):
                assert not await module.async_migrate_legacy_token_file(hass, entry, path)
        finally:
            resume.set()
            await reset
    assert "token" not in entry.data
    assert module.CONF_LEGACY_TOKEN_FILES not in entry.data


async def test_legacy_read_tolerates_a_source_deleted_before_open(tmp_path) -> None:
    module = _module()
    hass = _FakeHass(tmp_path)
    source = module.LegacyFileTokenStore(hass, ".storage/stiebel_dhe_connect_token_dhe_8443.txt")
    await source.async_save_token("legacy-token-value-000001")
    with patch("builtins.open", side_effect=FileNotFoundError):
        assert await source.async_load_token() == ""


@pytest.mark.parametrize("error", [PermissionError, asyncio.CancelledError])
async def test_failed_pairing_reset_does_not_leave_migration_blocked(tmp_path, error) -> None:
    module = _module()
    hass = _FakeHass(tmp_path)
    entry = SimpleNamespace(entry_id="entry-1", data={})
    path = ".storage/stiebel_dhe_connect_token_dhe_8443.txt"
    await module.LegacyFileTokenStore(hass, path).async_save_token("legacy-token-value-000001")
    await module.async_migrate_legacy_token_file(hass, entry, path)
    with (
        patch.object(module.LegacyFileTokenStore, "async_clear_token", side_effect=error),
        pytest.raises(error),
    ):
        await module.ConfigEntryTokenStore(hass, entry).async_clear_token()
    with patch.object(module.LegacyFileTokenStore, "async_load_token", new=AsyncMock(return_value="legacy-token-value-000001")) as read:
        assert not await module.async_migrate_legacy_token_file(hass, entry, path)
        read.assert_awaited_once()
    await module.ConfigEntryTokenStore(hass, entry).async_clear_token()
    assert "token" not in entry.data


async def test_overlapping_resets_block_only_their_entry_until_both_complete(tmp_path) -> None:
    module = _module()
    hass = _FakeHass(tmp_path)
    entry = SimpleNamespace(entry_id="entry-1", data={})
    other_entry = SimpleNamespace(entry_id="entry-2", data={})
    path = ".storage/stiebel_dhe_connect_token_dhe_8443.txt"
    other_path = ".storage/stiebel_dhe_connect_token_other_8443.txt"
    for source_path in (path, other_path):
        await module.LegacyFileTokenStore(hass, source_path).async_save_token("legacy-token-value-000001")
    await module.async_migrate_legacy_token_file(hass, entry, path)
    started = [asyncio.Event(), asyncio.Event()]
    resume = [asyncio.Event(), asyncio.Event()]
    calls = 0
    original_clear = module.LegacyFileTokenStore.async_clear_token

    async def paused_clear(store):
        nonlocal calls
        index = calls
        calls += 1
        started[index].set()
        await resume[index].wait()
        await original_clear(store)

    resets = []
    with patch.object(module.LegacyFileTokenStore, "async_clear_token", paused_clear):
        try:
            for index in range(2):
                resets.append(asyncio.create_task(module.ConfigEntryTokenStore(hass, entry).async_clear_token()))
                await asyncio.wait_for(started[index].wait(), timeout=5)
            assert await module.async_migrate_legacy_token_file(hass, other_entry, other_path)
            resume[0].set()
            await resets[0]
            with patch.object(module.LegacyFileTokenStore, "async_load_token", side_effect=AssertionError("read during reset")):
                assert not await module.async_migrate_legacy_token_file(hass, entry, path)
        finally:
            for event in resume:
                event.set()
            await asyncio.gather(*resets)
    with patch.object(module.LegacyFileTokenStore, "async_load_token", new=AsyncMock(return_value="")) as read:
        assert not await module.async_migrate_legacy_token_file(hass, entry, path)
        read.assert_awaited_once()


@pytest.mark.parametrize("cleanup_kind", ["malformed", "persisted"])
async def test_pairing_reset_invalidates_migration_during_file_deletion(tmp_path, cleanup_kind) -> None:
    module = _module()
    hass = _FakeHass(tmp_path)
    entry = SimpleNamespace(entry_id="entry-1", data={})
    path = ".storage/stiebel_dhe_connect_token_dhe_8443.txt"
    extra_path = ".storage/stiebel_dhe_connect_token_extra_8443.txt"
    await module.LegacyFileTokenStore(hass, path).async_save_token("legacy-token-value-000001")
    await module.async_migrate_legacy_token_file(hass, entry, path)
    if cleanup_kind == "persisted":
        hass = _FakeHass(tmp_path)
        paths = (path,)
        paused_path = path
    else:
        await module.LegacyFileTokenStore(hass, extra_path).async_save_token("malformed")
        paths = (path, extra_path)
        paused_path = extra_path
    deleting, resume = asyncio.Event(), asyncio.Event()
    original_clear = module.LegacyFileTokenStore.async_clear_token

    async def paused_clear(store):
        if store.token_path == hass.config.path(paused_path) and not deleting.is_set():
            deleting.set()
            await resume.wait()
        await original_clear(store)

    with patch.object(module.LegacyFileTokenStore, "async_clear_token", paused_clear):
        migration = asyncio.create_task(module.async_migrate_legacy_token_files(hass, entry, paths))
        try:
            await asyncio.wait_for(deleting.wait(), timeout=5)
            await module.ConfigEntryTokenStore(hass, entry).async_clear_token()
            if cleanup_kind == "persisted":
                await module.ConfigEntryTokenStore(hass, entry).async_save_token("fresh-token-value-000001")
                await module.LegacyFileTokenStore(hass, extra_path).async_save_token("fresh-legacy-token-000001")
                assert not await module.async_migrate_legacy_token_file(hass, entry, extra_path)
            expected_data = dict(entry.data)
        finally:
            resume.set()
            migrated = await migration
    assert not migrated
    assert entry.data == expected_data
    if cleanup_kind == "persisted":
        assert entry.data[module.CONF_LEGACY_TOKEN_FILES] == [Path(extra_path).name]
        assert entry.data["token"] == "fresh-token-value-000001"
    else:
        assert "token" not in entry.data
        assert module.CONF_LEGACY_TOKEN_FILES not in entry.data


@pytest.mark.parametrize("cancel_migration", [False, True])
async def test_reset_retires_unregistered_destination_source(tmp_path, cancel_migration) -> None:
    module = _module()
    hass = _FakeHass(tmp_path)
    entry = SimpleNamespace(entry_id="entry-1", data={})
    old_path = ".storage/stiebel_dhe_connect_token_old_8443.txt"
    new_path = ".storage/stiebel_dhe_connect_token_new_8443.txt"
    for path in (old_path, new_path):
        await module.LegacyFileTokenStore(hass, path).async_save_token("legacy-token-value-000001")
    await module.async_migrate_legacy_token_file(hass, entry, old_path)
    reading, resume = asyncio.Event(), asyncio.Event()
    original_load = module.LegacyFileTokenStore.async_load_token

    async def paused_load(store):
        token = await original_load(store)
        if store.token_path == hass.config.path(new_path):
            reading.set()
            await resume.wait()
        return token

    with patch.object(module.LegacyFileTokenStore, "async_load_token", paused_load):
        migration = asyncio.create_task(module.async_migrate_legacy_token_files(hass, entry, (new_path, old_path)))
        try:
            await asyncio.wait_for(reading.wait(), timeout=5)
            await module.ConfigEntryTokenStore(hass, entry).async_clear_token()
            if cancel_migration:
                migration.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await migration
        finally:
            resume.set()
            if not migration.cancelled():
                assert not await migration

    assert "token" not in entry.data
    assert not Path(hass.config.path(new_path)).exists()
    assert not Path(hass.config.path(old_path)).exists()
    assert not await module.async_migrate_legacy_token_file(_FakeHass(tmp_path), entry, new_path)


async def test_reset_includes_destination_added_while_deletion_is_pending(tmp_path) -> None:
    module = _module()
    hass = _FakeHass(tmp_path)
    entry = SimpleNamespace(entry_id="entry-1", data={})
    old_path = ".storage/stiebel_dhe_connect_token_old_8443.txt"
    new_path = ".storage/stiebel_dhe_connect_token_new_8443.txt"
    for path in (old_path, new_path):
        await module.LegacyFileTokenStore(hass, path).async_save_token("legacy-token-value-000001")
    await module.async_migrate_legacy_token_file(hass, entry, old_path)
    deleting, resume = asyncio.Event(), asyncio.Event()
    original_clear = module.LegacyFileTokenStore.async_clear_token

    async def paused_clear(store):
        if store.token_path == hass.config.path(old_path):
            deleting.set()
            await resume.wait()
        await original_clear(store)

    with patch.object(module.LegacyFileTokenStore, "async_clear_token", paused_clear):
        reset = asyncio.create_task(module.ConfigEntryTokenStore(hass, entry).async_clear_token())
        try:
            await asyncio.wait_for(deleting.wait(), timeout=5)
            assert not await module.async_migrate_legacy_token_file(hass, entry, new_path)
        finally:
            resume.set()
            await reset
    assert not Path(hass.config.path(new_path)).exists()
    assert not await module.async_migrate_legacy_token_file(_FakeHass(tmp_path), entry, new_path)


@pytest.mark.parametrize("first_finished", [0, 1])
@pytest.mark.parametrize("fresh_token", ["fresh-token-value-000001", "legacy-token-value-000001"])
async def test_older_overlapping_reset_preserves_new_token_write(tmp_path, first_finished, fresh_token) -> None:
    module = _module()
    hass = _FakeHass(tmp_path)
    entry = SimpleNamespace(entry_id="entry-1", data={})
    path = ".storage/stiebel_dhe_connect_token_dhe_8443.txt"
    await module.LegacyFileTokenStore(hass, path).async_save_token("legacy-token-value-000001")
    await module.async_migrate_legacy_token_file(hass, entry, path)
    started = [asyncio.Event(), asyncio.Event()]
    resume = [asyncio.Event(), asyncio.Event()]
    calls = 0
    original_clear = module.LegacyFileTokenStore.async_clear_token

    async def paused_clear(store):
        nonlocal calls
        index = calls
        calls += 1
        started[index].set()
        await resume[index].wait()
        await original_clear(store)

    resets = []
    with patch.object(module.LegacyFileTokenStore, "async_clear_token", paused_clear):
        try:
            for index in range(2):
                resets.append(asyncio.create_task(module.ConfigEntryTokenStore(hass, entry).async_clear_token()))
                await asyncio.wait_for(started[index].wait(), timeout=5)
            resume[first_finished].set()
            await resets[first_finished]
            await module.ConfigEntryTokenStore(hass, entry).async_save_token(fresh_token)
        finally:
            for event in resume:
                event.set()
            await asyncio.gather(*resets)
    assert entry.data["token"] == fresh_token
    assert module.CONF_LEGACY_TOKEN_FILES not in entry.data
    assert not await module.async_migrate_legacy_token_file(_FakeHass(tmp_path), entry, path)
    assert entry.data["token"] == fresh_token
    await module.ConfigEntryTokenStore(hass, entry).async_clear_token()
    assert "token" not in entry.data


@pytest.mark.parametrize("write_kind", ["fresh", "same", "failed", "metadata"])
async def test_pending_reset_preserves_only_successful_token_writes(tmp_path, write_kind) -> None:
    module = _module()
    hass = _FakeHass(tmp_path)
    entry = SimpleNamespace(entry_id="entry-1", data={})
    path = ".storage/stiebel_dhe_connect_token_dhe_8443.txt"
    old_token = "legacy-token-value-000001"
    await module.LegacyFileTokenStore(hass, path).async_save_token(old_token)
    await module.async_migrate_legacy_token_file(hass, entry, path)
    deleting, resume = asyncio.Event(), asyncio.Event()
    original_clear = module.LegacyFileTokenStore.async_clear_token

    async def paused_clear(store):
        deleting.set()
        await resume.wait()
        await original_clear(store)

    with patch.object(module.LegacyFileTokenStore, "async_clear_token", paused_clear):
        reset = asyncio.create_task(module.ConfigEntryTokenStore(hass, entry).async_clear_token())
        try:
            await asyncio.wait_for(deleting.wait(), timeout=5)
            if write_kind == "failed":
                with patch.object(hass.config_entries, "async_update_entry", side_effect=RuntimeError), pytest.raises(RuntimeError):
                    await module.ConfigEntryTokenStore(hass, entry).async_save_token("fresh-token-value-000001")
            elif write_kind == "metadata":
                hass.config_entries.async_update_entry(entry, data={**entry.data, "name": "Renamed"})
            else:
                token = old_token if write_kind == "same" else "fresh-token-value-000001"
                await module.ConfigEntryTokenStore(hass, entry).async_save_token(token)
        finally:
            resume.set()
            await reset
    assert module.CONF_LEGACY_TOKEN_FILES not in entry.data
    if write_kind in {"fresh", "same"}:
        assert entry.data["token"] == token
    else:
        assert "token" not in entry.data
    if write_kind == "metadata":
        assert entry.data["name"] == "Renamed"


@pytest.mark.parametrize("error", [PermissionError, asyncio.CancelledError])
async def test_reset_retry_keeps_sources_after_migration_is_cancelled(tmp_path, error) -> None:
    module = _module()
    hass = _FakeHass(tmp_path)
    entry = SimpleNamespace(entry_id="entry-1", data={})
    path = ".storage/stiebel_dhe_connect_token_new_8443.txt"
    await module.LegacyFileTokenStore(hass, path).async_save_token("legacy-token-value-000001")
    reading = asyncio.Event()
    original_load = module.LegacyFileTokenStore.async_load_token

    async def paused_load(store):
        token = await original_load(store)
        reading.set()
        await asyncio.Event().wait()
        return token

    with patch.object(module.LegacyFileTokenStore, "async_load_token", paused_load):
        migration = asyncio.create_task(module.async_migrate_legacy_token_file(hass, entry, path))
        try:
            await asyncio.wait_for(reading.wait(), timeout=5)
            with patch.object(module.LegacyFileTokenStore, "async_clear_token", side_effect=error), pytest.raises(error):
                await module.ConfigEntryTokenStore(hass, entry).async_clear_token()
        finally:
            migration.cancel()
            with pytest.raises(asyncio.CancelledError):
                await migration
    assert module.owned_legacy_token_paths(hass, entry) == (hass.config.path(path),)
    assert not module._token_reset_state(hass, entry).migration_sources
    await module.ConfigEntryTokenStore(hass, entry).async_clear_token()
    assert not Path(hass.config.path(path)).exists()
    assert module.owned_legacy_token_paths(hass, entry) == ()
    assert not await module.async_migrate_legacy_token_file(_FakeHass(tmp_path), entry, path)


async def test_empty_token_save_uses_the_reset_cleanup_path(tmp_path) -> None:
    module = _module()
    hass = _FakeHass(tmp_path)
    entry = SimpleNamespace(entry_id="entry-1", data={})
    path = ".storage/stiebel_dhe_connect_token_dhe_8443.txt"
    await module.LegacyFileTokenStore(hass, path).async_save_token("legacy-token-value-000001")
    await module.async_migrate_legacy_token_file(hass, entry, path)
    await module.ConfigEntryTokenStore(hass, entry).async_save_token(" ")
    assert "token" not in entry.data
    assert not Path(hass.config.path(path)).exists()
    assert module.owned_legacy_token_paths(hass, entry) == ()


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
