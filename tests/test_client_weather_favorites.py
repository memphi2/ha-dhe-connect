"""Behavior tests for weather favorites in the DHE client."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import types
import stat
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
COMPONENT_DIR = ROOT / "custom_components" / "stiebel_dhe_connect"
PACKAGE_NAME = "custom_components.stiebel_dhe_connect"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_component_module(module_name: str):
    root_module_name = "custom_components"
    if root_module_name not in sys.modules:
        root_module = types.ModuleType(root_module_name)
        root_module.__path__ = [str(ROOT / root_module_name)]
        sys.modules[root_module_name] = root_module

    package = sys.modules.get(PACKAGE_NAME)
    if package is None:
        package = types.ModuleType(PACKAGE_NAME)
        package.__path__ = [str(COMPONENT_DIR)]
        package.__package__ = root_module_name
        sys.modules[PACKAGE_NAME] = package

    module_filename = COMPONENT_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE_NAME}.{module_name}",
        module_filename,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[f"{PACKAGE_NAME}.{module_name}"] = module
    spec.loader.exec_module(module)
    return module


def _load_client():
    _load_component_module("client_mapping")
    _load_component_module("flow_helpers")
    _load_component_module("pairing_helpers")
    _load_component_module("protocol")
    return _load_component_module("client")


class TestClientWeatherFavorites(unittest.IsolatedAsyncioTestCase):
    """Validate weather-favorite toggle safeguards."""

    async def test_add_weather_favorite_existing_and_refresh_timeout_no_toggle(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError
        client = DHEClient.__new__(DHEClient)
        location = {"LocationId": "ID=1", "Name": "Essen"}

        client._last_weather_state = {
            "favorites": [location],
        }
        client._weather_favorites = lambda: [location]
        client._request_weather_favorites = AsyncMock(side_effect=DHEError("timeout"))
        client._assign_weather_favorite_and_wait = AsyncMock(
            side_effect=AssertionError("must not toggle existing favorite")
        )
        client._send_ste_command = AsyncMock()
        client._wait_for_weather_location = AsyncMock()

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry

        result = await DHEClient.add_weather_favorite(client, location)

        self.assertTrue(result)
        client._request_weather_favorites.assert_awaited_once()
        client._assign_weather_favorite_and_wait.assert_not_awaited()
        client._send_ste_command.assert_not_awaited()
        client._wait_for_weather_location.assert_not_awaited()

    async def test_pairing_notification_ids_include_port(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        client_a = DHEClient.__new__(DHEClient)
        client_a.host = "dhe.local"
        client_a.port = 8443

        client_b = DHEClient.__new__(DHEClient)
        client_b.host = "dhe.local"
        client_b.port = 9443

        self.assertNotEqual(
            client_a._pairing_notification_id,
            client_b._pairing_notification_id,
        )
        self.assertNotEqual(
            client_a._pairing_confirmation_notification_id,
            client_b._pairing_confirmation_notification_id,
        )

    async def test_set_price_rolls_back_when_second_write_fails(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError

        client = DHEClient.__new__(DHEClient)
        euros_id = 100
        cents_id = 101
        client._last_measurements = {
            euros_id: 0.0,
            cents_id: 29.0,
        }

        calls: list[tuple[int, float]] = []

        async def _write_odb_value(odb_id: int, value):
            calls.append((odb_id, float(value)))
            if (odb_id, float(value)) == (cents_id, 5.0):
                raise DHEError("write failed")
            return float(value)

        client.write_odb_value = AsyncMock(side_effect=_write_odb_value)

        with self.assertRaises(DHEError):
            await DHEClient._set_price(
                client,
                1.05,
                euros_id,
                cents_id,
                max_value=9.99,
            )

        self.assertEqual(
            calls,
            [
                (euros_id, 1.0),
                (cents_id, 5.0),
                (euros_id, 0.0),
                (cents_id, 29.0),
            ],
        )

    async def test_save_token_creates_restrictive_file(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        class _FakeHass:
            async def async_add_executor_job(self, func, *args):
                return func(*args)

        client = DHEClient.__new__(DHEClient)
        client.hass = _FakeHass()
        client._token = None

        with tempfile.TemporaryDirectory() as temp_dir:
            client.token_path = os.path.join(temp_dir, "token.txt")
            await DHEClient._save_token(client, "super-secret-token")

            with open(client.token_path, "r", encoding="utf-8") as file:
                self.assertEqual(file.read(), "super-secret-token")

            if os.name == "posix":
                mode = stat.S_IMODE(os.stat(client.token_path).st_mode)
                self.assertEqual(mode, stat.S_IRUSR | stat.S_IWUSR)

    async def test_set_temperature_memory_requires_confirmed_value(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError

        client = DHEClient.__new__(DHEClient)
        client._last_measurement_attributes = {}
        client._temperature_memory_ids = lambda _slot: (0, 700)
        client._refresh_temperature_memories = AsyncMock()
        client._temperature_memory_payload = lambda *_args, **_kwargs: {
            "name": "Dusche",
            "temperature": 38.0,
            "operation": "add_change",
        }
        client._post_packet = AsyncMock()
        client._message_packet = lambda payload: payload
        client._cached_temperature_memory_temperature = lambda _measurement_id: None

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry

        with self.assertRaisesRegex(DHEError, "was not confirmed"):
            await DHEClient.set_temperature_memory(client, 0, 38.0)


if __name__ == "__main__":
    unittest.main()
