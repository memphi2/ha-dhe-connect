"""Tests for setup/repair pairing validation helpers."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import types
import unittest

try:
    from tests.test_client_weather_favorites import (
        _load_client,
        _load_component_module,
    )
except ModuleNotFoundError:
    from test_client_weather_favorites import (  # type: ignore[no-redef]
        _load_client,
        _load_component_module,
    )


def _load_pairing_validation():
    _load_client()
    _load_component_module("config_entry_helpers")
    _load_component_module("config_flow_discovery")
    _load_component_module("token_file_helpers")
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

    def test_configured_token_paths_includes_entry_and_target_paths(self) -> None:
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
                    os.path.abspath(root / ".storage/stiebel_dhe_connect_token_entry-one.txt")
                ),
                paths,
            )
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
                data={"host": "configured.local", "port": 8443},
                options={},
            )
            hass = _FakeHass(root, [configured_entry])
            remove_paths = (
                storage / "stiebel_dhe_connect_token.txt",
                storage / "stiebel_dhe_connect_token_new.local_8443.txt",
                storage / "stiebel_dhe_connect_token_stale_8443.txt",
            )
            keep_path = storage / "stiebel_dhe_connect_token_configured.local_8443.txt"
            unrelated_path = storage / "other.txt"
            for path in (*remove_paths, keep_path, unrelated_path):
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

        class _SuccessfulClient:
            diagnostic_state: dict[str, object] = {}
            last_device_info = {"wlan_mac": "AA-BB-CC-DD-EE-FF"}

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
        self.assertEqual(result.unique_id, "aa:bb:cc:dd:ee:ff")

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
