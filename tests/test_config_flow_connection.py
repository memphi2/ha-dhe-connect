"""Tests for shared connection flow helpers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

from homeassistant.const import CONF_HOST, CONF_PORT

from custom_components.stiebel_dhe_connect.config_flow_connection import (
    async_preserve_token_for_retarget,
    connection_options_for_entry,
)
from custom_components.stiebel_dhe_connect.const import DEFAULT_PORT
from custom_components.stiebel_dhe_connect.token_file_helpers import token_file_for_target


class _FakeConfig:
    def __init__(self, base_path: Path) -> None:
        self._base_path = base_path

    def path(self, relative_path: str = "") -> str:
        return str((self._base_path / relative_path).resolve())


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


class _FakeConfigEntries:
    def __init__(self) -> None:
        self.update_calls: list[dict[str, object]] = []

    def async_update_entry(
        self,
        entry: SimpleNamespace,
        *,
        data: dict[str, object] | None = None,
        options: dict[str, object] | None = None,
    ) -> bool:
        if data is not None:
            entry.data = data
        if options is not None:
            entry.options = options
        self.update_calls.append({"entry": entry, "data": data, "options": options})
        return True


def _fake_entry(
    *,
    host: str = "old-dhe.local",
    port: int = DEFAULT_PORT,
    options: dict[str, object] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        data={
            CONF_HOST: host,
            CONF_PORT: port,
        },
        options=options or {},
        entry_id="entry-123",
    )


def test_connection_options_for_entry_merges_existing_options() -> None:
    entry = _fake_entry(options={"keep": "value", CONF_HOST: "legacy.local"})
    merged = connection_options_for_entry(
        entry,
        {
            CONF_HOST: "new-dhe.local",
            CONF_PORT: 9443,
        },
    )

    assert merged["keep"] == "value"
    assert merged[CONF_HOST] == "new-dhe.local"
    assert merged[CONF_PORT] == 9443


async def test_async_preserve_token_for_retarget_migrates_existing_token(
    tmp_path,
) -> None:
    hass = _FakeHass(tmp_path)
    entry = _fake_entry()
    token = "existing-token-value-0001"
    old_token = Path(
        hass.config.path(token_file_for_target("old-dhe.local", DEFAULT_PORT))
    )
    new_token = Path(
        hass.config.path(token_file_for_target("new-dhe.local", DEFAULT_PORT))
    )
    old_token.parent.mkdir(parents=True, exist_ok=True)
    old_token.write_text(token, encoding="utf-8")
    assert not new_token.exists()

    migrated = await async_preserve_token_for_retarget(
        hass,
        entry,
        {
            CONF_HOST: "new-dhe.local",
            CONF_PORT: DEFAULT_PORT,
        },
    )

    assert migrated is True
    assert entry.data["token"] == token
    assert not old_token.exists()
    assert not new_token.exists()


async def test_async_preserve_token_for_retarget_deletes_stale_files_when_token_exists(
    tmp_path,
) -> None:
    hass = _FakeHass(tmp_path)
    entry = _fake_entry()
    entry.data["token"] = "entry-token-value-000001"
    old_token = Path(
        hass.config.path(token_file_for_target("old-dhe.local", DEFAULT_PORT))
    )
    new_token = Path(
        hass.config.path(token_file_for_target("new-dhe.local", DEFAULT_PORT))
    )
    old_token.parent.mkdir(parents=True, exist_ok=True)
    old_token.write_text("legacy-old-token-value-001", encoding="utf-8")
    new_token.write_text("legacy-new-token-value-001", encoding="utf-8")

    migrated = await async_preserve_token_for_retarget(
        hass,
        entry,
        {
            CONF_HOST: "new-dhe.local",
            CONF_PORT: DEFAULT_PORT,
        },
    )

    assert migrated is False
    assert entry.data["token"] == "entry-token-value-000001"
    assert not old_token.exists()
    assert not new_token.exists()


async def test_async_preserve_token_for_retarget_skips_when_target_is_unchanged(
    tmp_path,
    monkeypatch,
) -> None:
    hass = _FakeHass(tmp_path)
    entry = _fake_entry()

    async def _fail_migrate(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("migration must not run for unchanged target")

    monkeypatch.setattr(
        "custom_components.stiebel_dhe_connect.config_flow_connection.async_migrate_legacy_token_files",
        _fail_migrate,
    )

    migrated = await async_preserve_token_for_retarget(
        hass,
        entry,
        {
            CONF_HOST: "old-dhe.local",
            CONF_PORT: DEFAULT_PORT,
        },
    )

    assert migrated is False


async def test_async_preserve_token_for_retarget_returns_false_without_valid_target(
    tmp_path,
) -> None:
    hass = _FakeHass(tmp_path)
    entry = _fake_entry()
    entry.data = {}

    migrated = await async_preserve_token_for_retarget(
        hass,
        entry,
        {
            CONF_HOST: "new-dhe.local",
            CONF_PORT: DEFAULT_PORT,
        },
    )

    assert migrated is False


async def test_async_preserve_token_for_retarget_skips_when_target_matches_default_port(
    tmp_path,
) -> None:
    hass = _FakeHass(tmp_path)
    entry = _fake_entry()

    migrated = await async_preserve_token_for_retarget(
        hass,
        entry,
        {
            CONF_HOST: "old-dhe.local",
            CONF_PORT: 8443,
        },
    )

    assert migrated is False
