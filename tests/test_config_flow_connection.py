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

    async def async_add_executor_job(
        self,
        func: Callable[..., object],
        *args: object,
    ) -> object:
        return func(*args)


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


async def test_async_preserve_token_for_retarget_copies_existing_token(
    tmp_path,
) -> None:
    hass = _FakeHass(tmp_path)
    entry = _fake_entry()
    old_token = Path(hass.config.path(token_file_for_target("old-dhe.local", DEFAULT_PORT)))
    new_token = Path(hass.config.path(token_file_for_target("new-dhe.local", DEFAULT_PORT)))
    old_token.parent.mkdir(parents=True, exist_ok=True)
    old_token.write_text("token-value", encoding="utf-8")
    assert not new_token.exists()

    copied = await async_preserve_token_for_retarget(
        hass,
        entry,
        {
            CONF_HOST: "new-dhe.local",
            CONF_PORT: DEFAULT_PORT,
        },
    )

    assert copied is True
    assert new_token.read_text(encoding="utf-8") == "token-value"


async def test_async_preserve_token_for_retarget_ignores_copy_errors(
    tmp_path,
    monkeypatch,
) -> None:
    hass = _FakeHass(tmp_path)
    entry = _fake_entry()
    old_token = Path(hass.config.path(token_file_for_target("old-dhe.local", DEFAULT_PORT)))
    new_token = Path(hass.config.path(token_file_for_target("new-dhe.local", DEFAULT_PORT)))
    old_token.parent.mkdir(parents=True, exist_ok=True)
    old_token.write_text("token-value", encoding="utf-8")

    def _raise_copy(*_args: object, **_kwargs: object) -> None:
        raise OSError("copy failed")

    monkeypatch.setattr(
        "custom_components.stiebel_dhe_connect.config_flow_connection.shutil.copy2",
        _raise_copy,
    )

    copied = await async_preserve_token_for_retarget(
        hass,
        entry,
        {
            CONF_HOST: "new-dhe.local",
            CONF_PORT: DEFAULT_PORT,
        },
    )

    assert copied is False
    assert not new_token.exists()


async def test_async_preserve_token_for_retarget_skips_when_target_is_unchanged(
    tmp_path,
    monkeypatch,
) -> None:
    hass = _FakeHass(tmp_path)
    entry = _fake_entry()

    def _fail_copy(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("copy must not run for unchanged target")

    monkeypatch.setattr(
        "custom_components.stiebel_dhe_connect.config_flow_connection.shutil.copy2",
        _fail_copy,
    )

    copied = await async_preserve_token_for_retarget(
        hass,
        entry,
        {
            CONF_HOST: "OLD-DHE.local.",
            CONF_PORT: DEFAULT_PORT,
        },
    )

    assert copied is False


async def test_async_preserve_token_for_retarget_returns_false_without_valid_target(
    tmp_path,
) -> None:
    hass = _FakeHass(tmp_path)
    entry = _fake_entry()
    entry.data = {}

    copied = await async_preserve_token_for_retarget(
        hass,
        entry,
        {
            CONF_HOST: "new-dhe.local",
            CONF_PORT: DEFAULT_PORT,
        },
    )

    assert copied is False


async def test_async_preserve_token_for_retarget_skips_when_paths_match(
    tmp_path,
) -> None:
    hass = _FakeHass(tmp_path)
    entry = _fake_entry()
    old_token = Path(hass.config.path(token_file_for_target("old-dhe.local", DEFAULT_PORT)))
    old_token.parent.mkdir(parents=True, exist_ok=True)
    old_token.write_text("token-value", encoding="utf-8")

    copied = await async_preserve_token_for_retarget(
        hass,
        entry,
        {
            CONF_HOST: "old-dhe.local",
            CONF_PORT: 8443,
        },
    )

    assert copied is False
