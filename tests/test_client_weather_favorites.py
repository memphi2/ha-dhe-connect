"""Behavior tests for weather favorites in the DHE client."""

from __future__ import annotations

import stat
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock
import importlib.util
import os
from pathlib import Path
import types

ROOT = Path(__file__).resolve().parents[1]
COMPONENT_DIR = ROOT / "custom_components" / "stiebel_dhe_connect"
PACKAGE_NAME = "custom_components.stiebel_dhe_connect"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from tests.test_aiohttp_stubs import _ensure_aiohttp_stub
except ModuleNotFoundError:
    from test_aiohttp_stubs import _ensure_aiohttp_stub


def _load_component_module(module_name: str):
    _ensure_aiohttp_stub()
    try:
        from tests.test_ha_stubs import ensure_homeassistant_stubs
    except ModuleNotFoundError:
        from test_ha_stubs import ensure_homeassistant_stubs

    ensure_homeassistant_stubs()
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

    async def test_add_weather_favorite_missing_in_stale_cache_fails_safely(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError
        client = DHEClient.__new__(DHEClient)
        location = {"LocationId": "ID=2", "Name": "Stuttgart"}
        cached_location = {"LocationId": "ID=1", "Name": "Essen"}

        client._last_weather_state = {
            "favorites": [cached_location],
        }
        client._weather_favorites = lambda: [cached_location]
        client._request_weather_favorites = AsyncMock(side_effect=DHEError("timeout"))
        client._assign_weather_favorite_and_wait = AsyncMock(
            side_effect=AssertionError("must not toggle when cache is stale")
        )
        client._send_ste_command = AsyncMock()
        client._wait_for_weather_location = AsyncMock()

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry

        with self.assertRaisesRegex(
            DHEError,
            "Cannot safely add DHE weather favorite without a fresh favorite list",
        ):
            await DHEClient.add_weather_favorite(client, location)

        client._request_weather_favorites.assert_awaited_once()
        client._assign_weather_favorite_and_wait.assert_not_awaited()
        client._send_ste_command.assert_not_awaited()
        client._wait_for_weather_location.assert_not_awaited()

    async def test_add_radio_favorite_existing_and_refresh_timeout_no_toggle(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError
        client = DHEClient.__new__(DHEClient)

        station = {"Id": 42, "Name": "WDR 2"}
        client._radio_favorites = lambda: [station]
        client._request_radio_favorites = AsyncMock(side_effect=DHEError("timeout"))
        client._assign_radio_favorite_and_wait = AsyncMock(
            side_effect=AssertionError("must not toggle existing favorite")
        )
        client._send_ste_command = AsyncMock()
        client._wait_for_radio_station = AsyncMock()

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry

        result = await DHEClient.add_radio_favorite(
            client,
            station,
            select=False,
        )

        self.assertTrue(result)
        client._request_radio_favorites.assert_awaited_once()
        client._assign_radio_favorite_and_wait.assert_not_awaited()
        client._send_ste_command.assert_not_awaited()

    async def test_add_radio_favorite_missing_in_stale_cache_fails_safely(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError
        client = DHEClient.__new__(DHEClient)

        station = {"Id": 42, "Name": "WDR 2"}
        cached_station = {"Id": 7, "Name": "NDR"}
        client._radio_favorites = lambda: [cached_station]
        client._request_radio_favorites = AsyncMock(side_effect=DHEError("timeout"))
        client._assign_radio_favorite_and_wait = AsyncMock(
            side_effect=AssertionError("must not toggle unknown station")
        )
        client._send_ste_command = AsyncMock()
        client._wait_for_radio_station = AsyncMock()

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry

        with self.assertRaisesRegex(
            DHEError,
            "Cannot safely add DHE radio favorite without a fresh favorite list",
        ):
            await DHEClient.add_radio_favorite(
                client,
                station,
                select=False,
            )

        client._request_radio_favorites.assert_awaited_once()
        client._assign_radio_favorite_and_wait.assert_not_awaited()
        client._send_ste_command.assert_not_awaited()

    async def test_remove_weather_favorite_existing_and_refresh_timeout_no_toggle(self) -> None:
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

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry

        with self.assertRaisesRegex(
            DHEError,
            "Cannot safely remove DHE weather favorite without a fresh favorite list",
        ):
            await DHEClient.remove_weather_favorite(client, location)

        client._request_weather_favorites.assert_awaited_once()
        client._assign_weather_favorite_and_wait.assert_not_awaited()

    async def test_remove_weather_favorite_missing_in_stale_cache_fails_safely(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError
        client = DHEClient.__new__(DHEClient)
        location = {"LocationId": "ID=2", "Name": "Stuttgart"}
        cached_location = {"LocationId": "ID=1", "Name": "Essen"}

        client._last_weather_state = {
            "favorites": [cached_location],
        }
        client._weather_favorites = lambda: [cached_location]
        client._request_weather_favorites = AsyncMock(side_effect=DHEError("timeout"))
        client._assign_weather_favorite_and_wait = AsyncMock(
            side_effect=AssertionError("must not toggle unknown location")
        )

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry

        with self.assertRaisesRegex(
            DHEError,
            "Cannot safely remove DHE weather favorite without a fresh favorite list",
        ):
            await DHEClient.remove_weather_favorite(client, location)

        client._request_weather_favorites.assert_awaited_once()
        client._assign_weather_favorite_and_wait.assert_not_awaited()

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

    async def test_notify_pairing_progress_cleans_up_legacy_pairing_notifications(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        class _FakeHass:
            pass

        client = DHEClient.__new__(DHEClient)
        client.hass = _FakeHass()
        client.host = "dhe.local"
        client.port = 9443

        client._pairing_notification_text = lambda _state: (
            "DHE Pairing",
            "waiting",
        )

        async_create = Mock()
        async_dismiss = Mock()

        client_module.persistent_notification.async_create = async_create
        client_module.persistent_notification.async_dismiss = async_dismiss

        client._notify_pairing_progress("connecting")

        self.assertEqual(
            async_dismiss.call_count,
            3,
            "Expected legacy and scoped pairing confirmation notifications to be dismissed",
        )
        async_dismiss.assert_any_call(
            client.hass,
            client._legacy_pairing_confirmation_notification_id,
        )
        async_dismiss.assert_any_call(
            client.hass,
            client._legacy_pairing_notification_id,
        )
        async_dismiss.assert_any_call(
            client.hass,
            client._pairing_confirmation_notification_id,
        )
        async_create.assert_called_once_with(
            client.hass,
            "waiting",
            title="DHE Pairing",
            notification_id=client._pairing_notification_id,
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
        client._temperature_memory_generation = 1
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

    async def test_set_temperature_memory_existing_slot_without_confirmation_is_rejected(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError

        client = DHEClient.__new__(DHEClient)
        client._temperature_memory_generation = 2
        client._last_measurement_attributes = {}
        client._temperature_memory_ids = lambda _slot: (0, 700)
        client._refresh_temperature_memories = AsyncMock()
        client._temperature_memory_payload = lambda *_args, **_kwargs: {
            "name": "Dusche",
            "temperature": 38.0,
            "id": 0,
            "operation": "add_change",
        }
        client._post_packet = AsyncMock()
        client._message_packet = lambda payload: payload
        client._cached_temperature_memory_temperature = lambda _measurement_id: 38.0
        client._handle_temperature_memory_item = unittest.mock.MagicMock()

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry

        with self.assertRaisesRegex(
            DHEError,
            "was not confirmed",
        ):
            await DHEClient.set_temperature_memory(client, 0, 38.0)

        self.assertEqual(client._temperature_memory_generation, 2)
        self.assertEqual(client._refresh_temperature_memories.await_count, 2)
        client._handle_temperature_memory_item.assert_not_called()

    async def test_set_temperature_memory_name_without_confirmation_is_rejected(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError

        client = DHEClient.__new__(DHEClient)
        client._temperature_memory_generation = 2
        client._last_measurement_attributes = {}
        client._temperature_memory_ids = lambda _slot: (0, 700)
        client._refresh_temperature_memories = AsyncMock()
        client._temperature_memory_payload = lambda *_args, **_kwargs: {
            "name": "Family",
            "temperature": 38.0,
            "id": 0,
            "operation": "add_change",
        }
        client._post_packet = AsyncMock()
        client._message_packet = lambda payload: payload
        client._cached_temperature_memory_temperature = lambda _measurement_id: 38.0

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry

        with self.assertRaisesRegex(
            DHEError,
            "name was not confirmed",
        ):
            await DHEClient.set_temperature_memory_name(
                client,
                0,
                "Family",
            )

        self.assertEqual(client._temperature_memory_generation, 2)
        self.assertEqual(client._refresh_temperature_memories.await_count, 2)

    async def test_set_temperature_memory_name_readback_mismatch_is_rejected(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError

        client = DHEClient.__new__(DHEClient)
        client._temperature_memory_generation = 0
        client._last_measurement_attributes = {}
        client._temperature_memory_ids = lambda _slot: (0, 700)

        async def _refresh_memory(_ctx: object | None = None) -> None:
            client._temperature_memory_generation += 1
            client._last_measurement_attributes[700] = {"name": "WrongName"}

        client._refresh_temperature_memories = AsyncMock(side_effect=_refresh_memory)
        client._temperature_memory_payload = lambda *_args, **_kwargs: {
            "name": "Family",
            "temperature": 38.0,
            "id": 0,
            "operation": "add_change",
        }
        client._post_packet = AsyncMock()
        client._message_packet = lambda payload: payload
        client._cached_temperature_memory_temperature = lambda _measurement_id: 38.0

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry

        with self.assertRaisesRegex(
            DHEError,
            "name readback was 'WrongName', expected 'Family'",
        ):
            await DHEClient.set_temperature_memory_name(
                client,
                0,
                "Family",
            )


if __name__ == "__main__":
    unittest.main()
