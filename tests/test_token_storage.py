"""Tests for DHE token storage backends."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

try:
    from tests.test_client_weather_favorites import _load_component_module
except ModuleNotFoundError:
    from test_client_weather_favorites import _load_component_module


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


async def test_migrate_legacy_token_file_moves_token_and_deletes_file(tmp_path) -> None:
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
    assert not legacy_file.exists()


async def test_migrate_legacy_token_file_deletes_file_when_entry_token_exists(
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
    assert not legacy_file.exists()
    assert hass.config_entries.update_calls == []


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
