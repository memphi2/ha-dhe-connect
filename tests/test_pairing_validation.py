"""Tests for setup/repair pairing validation helpers."""

from __future__ import annotations

import asyncio
import importlib
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from tests.client_test_support import (
        _load_client,
        _load_component_module,
    )
except ModuleNotFoundError:
    from client_test_support import (  # type: ignore[no-redef]
        _load_client,
        _load_component_module,
    )


def _load_pairing_validation():
    _load_client()
    _load_component_module("config_entry_helpers")
    _load_component_module("config_flow_discovery")
    _load_component_module("token_file_helpers")
    _load_component_module("token_storage")
    return _load_component_module("pairing_validation")


class _FakeConfig:
    def __init__(self, root: Path) -> None:
        self._root = root

    def path(self, value: str) -> str:
        return str(self._root / value)


class _FakeConfigEntries:
    def __init__(self, entries: list[types.SimpleNamespace]) -> None:
        self._entries = entries

    def async_entries(self, _domain: str) -> list[types.SimpleNamespace]:
        return list(self._entries)


class _FakeHass:
    def __init__(
        self,
        root: Path,
        entries: list[types.SimpleNamespace] | None = None,
    ) -> None:
        self.data = {}
        self.config = _FakeConfig(root)
        self.config_entries = _FakeConfigEntries(entries or [])

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class TestPairingValidation(unittest.IsolatedAsyncioTestCase):
    """Validate pairing helper cleanup and result mapping paths."""

    def setUp(self) -> None:
        self.module = _load_pairing_validation()

    def test_validation_path_getter_falls_back_without_ha_config(self) -> None:
        path = self.module._validation_path_getter(types.SimpleNamespace(), "token.txt")

        self.assertEqual(path, os.path.normcase(os.path.abspath("token.txt")))

    def test_configured_token_paths_includes_target_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            entry = types.SimpleNamespace(
                entry_id="entry-one",
                data={"host": "DHE.local.", "port": "8443"},
                options={},
            )
            hass = _FakeHass(root, [entry])

            paths = self.module._configured_token_paths(hass)

            self.assertIn(
                os.path.normcase(
                    os.path.abspath(root / ".storage/stiebel_dhe_connect_token_dhe.local_8443.txt")
                ),
                paths,
            )

    async def test_clear_setup_token_files_removes_stale_tokens_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = root / ".storage"
            storage.mkdir()
            configured_entry = types.SimpleNamespace(
                entry_id="configured",
                data={"host": "configured.local", "port": 8443,
                      "legacy_token_files": ["stiebel_dhe_connect_token_previous.local_8443.txt"]},
                options={},
            )
            hass = _FakeHass(root, [configured_entry])
            remove_paths = (
                storage / "stiebel_dhe_connect_token_new.local_8443.txt",
                storage / "stiebel_dhe_connect_token_stale_8443.txt",
            )
            keep_path = storage / "stiebel_dhe_connect_token_configured.local_8443.txt"
            unrelated_path = storage / "other.txt"
            pending_path = storage / configured_entry.data["legacy_token_files"][0]
            for path in (*remove_paths, keep_path, unrelated_path, pending_path):
                path.write_text("token", encoding="utf-8")

            await self.module._async_clear_setup_token_files(
                hass,
                "new.local",
                8443,
                ".storage/stiebel_dhe_connect_token_new.local_8443.txt",
            )

            for path in remove_paths:
                self.assertFalse(path.exists(), path)
            self.assertTrue(keep_path.exists())
            self.assertTrue(unrelated_path.exists())
            self.assertTrue(pending_path.exists())

    async def test_cleanup_keeps_inflight_unregistered_migration_sources(self) -> None:
        token_storage = importlib.import_module("custom_components.stiebel_dhe_connect.token_storage")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            entry = types.SimpleNamespace(entry_id="configured", data={"host": "old.local", "port": 8443}, options={})
            hass = _FakeHass(root, [entry])
            path = ".storage/stiebel_dhe_connect_token_destination_8443.txt"
            source = token_storage.LegacyFileTokenStore(hass, path)
            await source.async_save_token("synthetic-legacy-token-000001")
            reading = asyncio.Event()
            original_load = token_storage.LegacyFileTokenStore.async_load_token

            async def paused_load(store):
                token = await original_load(store)
                reading.set()
                await asyncio.Event().wait()
                return token

            with patch.object(token_storage.LegacyFileTokenStore, "async_load_token", paused_load):
                migration = asyncio.create_task(token_storage.async_migrate_legacy_token_file(hass, entry, path))
                try:
                    await asyncio.wait_for(reading.wait(), timeout=5)
                    await self.module._async_clear_setup_token_files(
                        hass, "unrelated.local", 8443,
                        ".storage/stiebel_dhe_connect_token_unrelated.local_8443.txt",
                    )
                    self.assertTrue(Path(source.token_path).exists())
                finally:
                    migration.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await migration
            self.assertEqual(token_storage.owned_legacy_token_paths(hass, entry), ())

    async def test_validate_setup_pairing_maps_validation_errors(self) -> None:
        module = self.module

        class _FailingClient:
            diagnostic_state = {"pairing_state": "waiting_for_confirmation"}
            last_device_info: dict[str, object] = {}

            def __init__(self, **_kwargs) -> None:
                pass

            async def validate_setup_authentication(self, *, timeout_seconds: float) -> None:
                self.timeout_seconds = timeout_seconds
                raise module.DHEError("pairing rejected")

        result = await module.validate_setup_pairing(
            types.SimpleNamespace(),
            "dhe.local",
            8443,
            ".storage/token.txt",
            client_factory=_FailingClient,
            error_mapper=lambda err, state: f"{type(err).__name__}:{state}",
            clear_setup_token_files=lambda *_args: _noop_async(),
        )

        self.assertEqual(result.error_key, "DHEError:waiting_for_confirmation")

    async def test_validate_setup_pairing_returns_mac_unique_id(self) -> None:
        module = self.module
        token_storage = _load_component_module("token_storage")
        token_store = token_storage.InMemoryTokenStore()
        captured_kwargs: dict[str, object] = {}

        class _SuccessfulClient:
            diagnostic_state: dict[str, object] = {}
            last_device_info = {"wlan_mac": "AA-BB-CC-DD-EE-FF"}

            def __init__(self, **kwargs) -> None:
                captured_kwargs.update(kwargs)

            async def validate_setup_authentication(self, *, timeout_seconds: float) -> None:
                self.timeout_seconds = timeout_seconds

        result = await module.validate_setup_pairing(
            types.SimpleNamespace(),
            "dhe.local",
            8443,
            ".storage/token.txt",
            token_store=token_store,
            client_factory=_SuccessfulClient,
            clear_setup_token_files=lambda *_args: _noop_async(),
        )

        self.assertIsNone(result.error_key)
        self.assertEqual(result.unique_id, "aa:bb:cc:dd:ee:ff")
        self.assertIs(captured_kwargs["token_store"], token_store)

    async def test_validate_setup_pairing_ignores_non_dict_device_info(self) -> None:
        module = self.module

        class _SuccessfulClient:
            diagnostic_state: dict[str, object] = {}
            last_device_info = "unexpected"

            def __init__(self, **_kwargs) -> None:
                pass

            async def validate_setup_authentication(self, *, timeout_seconds: float) -> None:
                self.timeout_seconds = timeout_seconds

        result = await module.validate_setup_pairing(
            types.SimpleNamespace(),
            "dhe.local",
            8443,
            ".storage/token.txt",
            client_factory=_SuccessfulClient,
            clear_setup_token_files=lambda *_args: _noop_async(),
        )

        self.assertIsNone(result.error_key)
        self.assertIsNone(result.unique_id)


async def _noop_async() -> None:
    return None


if __name__ == "__main__":
    unittest.main()
