"""Behavior tests for weather favorites in the DHE client."""

from __future__ import annotations

import asyncio
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
    _load_component_module("client_types")
    _load_component_module("client_mapping")
    _load_component_module("client_diagnostics")
    _load_component_module("client_errors")
    _load_component_module("client_constants")
    _load_component_module("connection_helpers")
    _load_component_module("engineio_helpers")
    _load_component_module("flow_helpers")
    _load_component_module("pairing_helpers")
    _load_component_module("protocol")
    _load_component_module("client_value_helpers")
    _load_component_module("device_info_helpers")
    _load_component_module("client_connection_supervisor")
    _load_component_module("client_callbacks")
    _load_component_module("client_connection_state")
    _load_component_module("client_pairing")
    _load_component_module("client_command_runner")
    _load_component_module("client_device_info_commands")
    _load_component_module("client_radio_commands")
    _load_component_module("client_weather_commands")
    _load_component_module("client_temperature_memory_commands")
    _load_component_module("client_wellness_timer_commands")
    _load_component_module("client_commands")
    _load_component_module("client_runtime_app")
    _load_component_module("client_runtime_media")
    _load_component_module("client_runtime")
    _load_component_module("client_web_version")
    _load_component_module("client_transport_helpers")
    _load_component_module("client_transport_auth")
    _load_component_module("client_transport")
    return _load_component_module("client")


def _load_protocol():
    return _load_component_module("protocol")


class TestClientWeatherFavorites(unittest.IsolatedAsyncioTestCase):
    """Validate weather-favorite toggle safeguards."""

    async def test_client_init_normalizes_host_and_url(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        client_module.async_get_clientsession = Mock(return_value=object())

        class _FakeConfig:
            def path(self, value: str) -> str:
                return f"/config/{value}"

        class _FakeHass:
            config = _FakeConfig()

        client = DHEClient(
            _FakeHass(),
            " http://[2001:db8::1]/ ",
            8443,
            ".storage/token.txt",
            "DHE",
        )

        self.assertEqual(client.host, "2001:db8::1")
        self.assertEqual(client._url_host, "[2001:db8::1]")
        self.assertEqual(client.base_url, "http://[2001:db8::1]:8443")
        self.assertEqual(client.token_path, "/config/.storage/token.txt")

    async def test_stop_cancels_runner_and_reconnect_grace_task(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        runner_task = asyncio.create_task(asyncio.sleep(60))
        grace_task = asyncio.create_task(asyncio.sleep(60))
        client = DHEClient.__new__(DHEClient)
        client._stopped = client_module.asyncio.Event()
        client._runner = runner_task
        client._ctx = None
        client._ready = client_module.asyncio.Event()
        client._ready.set()
        client._online = True
        client._available = True
        client._online_callbacks = set()
        client._availability_callbacks = set()
        client._diagnostic_callbacks = set()
        client._diagnostic_state = {}
        client._diagnostic_callbacks = set()
        client._last_message_monotonic = None
        client._notify_callbacks = Mock()
        client._reconnect_grace_task = grace_task

        await DHEClient.stop(client)

        self.assertTrue(runner_task.cancelled())
        self.assertTrue(grace_task.cancelled())
        self.assertIsNone(client._runner)
        self.assertIsNone(client._reconnect_grace_task)
        self.assertFalse(client._ready.is_set())
        self.assertFalse(client._online)
        self.assertFalse(client._available)
        self.assertEqual(client._diagnostic_state["connection_state"], "stopped")

    async def test_toggle_weather_favorite_does_not_retry(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError
        client = DHEClient.__new__(DHEClient)
        location = {"LocationId": "ID=1", "Name": "Essen"}

        client._command_lock = asyncio.Lock()
        client._ctx = object()
        client._ensure_ready = AsyncMock()
        client._assign_weather_favorite_and_wait = AsyncMock(
            side_effect=DHEError("confirmation timeout")
        )

        with self.assertRaisesRegex(
            DHEError,
            "Could not toggle DHE weather favorite: confirmation timeout",
        ):
            await DHEClient.toggle_weather_favorite(client, location)

        client._ensure_ready.assert_awaited_once()
        client._assign_weather_favorite_and_wait.assert_awaited_once_with(
            client._ctx,
            location,
        )

    async def test_command_retry_recovers_from_runtime_transport_errors(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        for message in (
            "socket closing",
            "socket write failed",
            "Session is closed",
            "transport lost",
        ):
            with self.subTest(message=message):
                client = DHEClient.__new__(DHEClient)

                client._command_lock = asyncio.Lock()
                client._ctx = object()
                client._ensure_ready = AsyncMock()
                client._force_reconnect = AsyncMock()
                attempts = 0

                async def _operation(_ctx, message=message):
                    nonlocal attempts
                    attempts += 1
                    if attempts == 1:
                        raise RuntimeError(message)
                    return "ok"

                result = await DHEClient._run_command_with_reconnect_retry(
                    client,
                    "Could not run command",
                    _operation,
                )

                self.assertEqual(result, "ok")
                self.assertEqual(attempts, 2)
                self.assertEqual(client._ensure_ready.await_count, 2)
                client._force_reconnect.assert_awaited_once()

    async def test_command_retry_does_not_retry_programming_runtime_errors(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        client = DHEClient.__new__(DHEClient)

        client._command_lock = asyncio.Lock()
        client._ctx = object()
        client._ensure_ready = AsyncMock()
        client._force_reconnect = AsyncMock()

        for message in ("unexpected invalid state", "socket handler invalid state"):
            with self.subTest(message=message):
                client._ensure_ready.reset_mock()
                client._force_reconnect.reset_mock()

                async def _operation(_ctx, message=message):
                    raise RuntimeError(message)

                with self.assertRaisesRegex(RuntimeError, message):
                    await DHEClient._run_command_with_reconnect_retry(
                        client,
                        "Could not run command",
                        _operation,
                    )

                client._ensure_ready.assert_awaited_once()
                client._force_reconnect.assert_not_awaited()

    async def test_add_weather_favorite_existing_and_refresh_timeout_no_toggle(
        self,
    ) -> None:
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

    async def test_add_weather_favorite_missing_in_stale_cache_fails_safely(
        self,
    ) -> None:
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

    async def test_add_radio_favorite_existing_and_refresh_timeout_no_toggle(
        self,
    ) -> None:
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

    async def test_remove_weather_favorite_existing_and_refresh_timeout_no_toggle(
        self,
    ) -> None:
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

    async def test_remove_weather_favorite_missing_in_stale_cache_fails_safely(
        self,
    ) -> None:
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
        target_fragment = client_a._pairing_notification_id.rsplit("_", 1)[-1]
        self.assertNotIn("dhe", target_fragment)
        self.assertNotIn("local", target_fragment)
        self.assertNotIn("8443", target_fragment)

    async def test_notify_pairing_progress_replaces_scoped_pairing_notifications(
        self,
    ) -> None:
        client_module = _load_client()
        pairing_module = sys.modules[f"{PACKAGE_NAME}.client_pairing"]
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

        pairing_module.persistent_notification.async_create = async_create
        pairing_module.persistent_notification.async_dismiss = async_dismiss

        client._notify_pairing_progress("connecting")

        self.assertEqual(async_dismiss.call_count, 2)
        async_dismiss.assert_any_call(
            client.hass,
            client._pairing_confirmation_notification_id,
        )
        async_dismiss.assert_any_call(
            client.hass,
            client._pairing_notification_id,
        )
        async_create.assert_called_once_with(
            client.hass,
            "waiting",
            title="DHE Pairing",
            notification_id=client._pairing_notification_id,
        )

    async def test_saving_monitor_updates_only_changed_category(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        client = DHEClient.__new__(DHEClient)
        client._last_saving_monitor_values = {
            "possible": {
                "water_l": 4.0,
                "energy_kwh": 1.5,
                "co2_kg": 0.2,
                "value_eur": 1.0,
            },
            "real": {
                "water_l": 2.0,
                "energy_kwh": 0.8,
                "co2_kg": 0.1,
                "value_eur": 0.4,
            },
        }
        calls: list[tuple[int, float, str, str]] = []

        def _capture_update(
            measurement_id: int,
            value: float,
            category: str,
            field: str,
        ) -> None:
            calls.append((measurement_id, value, category, field))

        client._update_saving_monitor_sensor = _capture_update

        DHEClient._handle_saving_monitor_value(
            client,
            "set:ste.app.savingMonitor:consumption",
            {
                "water_l": 12.34,
                "energy_Wh": 234.0,
                "emission_Co2Kg": 0.56,
                "value_E": 2.1,
            },
        )

        protocol_module = _load_protocol()
        expected_ids = set(
            protocol_module.SAVING_MONITOR_SENSOR_FIELDS["consumption"].values()
        )
        self.assertEqual({measurement_id for measurement_id, *_ in calls}, expected_ids)
        self.assertEqual({category for _, _, category, _ in calls}, {"consumption"})

    async def test_saving_monitor_attributes_do_not_include_other_categories(
        self,
    ) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient
        client = DHEClient.__new__(DHEClient)
        client._last_measurement_attributes = {}
        client._last_saving_monitor_values = {
            "activation_rate": 33.3,
            "possible": {"water_l": 1.0},
            "real": {"water_l": 2.0},
            "consumption": {"water_l": 3.0},
        }

        captured_calls: list[tuple[int, float, bool]] = []

        def _capture_measurement(
            odb_id: int,
            value: float,
            *,
            force_update: bool = False,
        ) -> None:
            captured_calls.append((odb_id, value, force_update))

        client._handle_measurement = _capture_measurement

        DHEClient._update_saving_monitor_sensor(
            client,
            protocol_module.ID_SAVING_MONITOR_POSSIBLE_WATER,
            1.0,
            "possible",
            "water_l",
        )

        attributes = client._last_measurement_attributes[
            protocol_module.ID_SAVING_MONITOR_POSSIBLE_WATER
        ]
        self.assertIn("possible", attributes)
        self.assertNotIn("real", attributes)
        self.assertNotIn("consumption", attributes)
        self.assertNotIn("activation_rate", attributes)
        self.assertEqual(
            captured_calls,
            [
                (
                    protocol_module.ID_SAVING_MONITOR_POSSIBLE_WATER,
                    1.0,
                    True,
                )
            ],
        )

    async def test_device_info_value_updates_device_info_measurement(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient
        client = DHEClient.__new__(DHEClient)
        client._last_app_values = {}
        client._last_device_info = {}
        client._last_measurement_attributes = {}
        captured_calls: list[tuple[int, str, bool]] = []

        def _capture_measurement(
            odb_id: int,
            value: str,
            *,
            force_update: bool = False,
        ) -> None:
            captured_calls.append((odb_id, value, force_update))

        client._handle_measurement = _capture_measurement

        DHEClient._handle_device_info_value(
            client,
            "set:ste.common.version:gadgetData",
            {
                "type": {"value": "DHE Connect"},
                "id": {"value": "device-1"},
                "wlan": {"value": "wifi-mac"},
                "bluetooth": {"value": "bt-mac"},
            },
        )

        attributes = client._last_measurement_attributes[protocol_module.ID_DEVICE_INFO]
        self.assertEqual(attributes["device_type"], "DHE Connect")
        self.assertEqual(attributes["device_id"], "device-1")
        self.assertEqual(attributes["product_id_prefix"], "device-")
        self.assertEqual(
            captured_calls,
            [(protocol_module.ID_DEVICE_INFO, "DHE Connect", True)],
        )

    async def test_device_info_text_values_skip_empty_payloads(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        client = DHEClient.__new__(DHEClient)
        client._last_app_values = {}
        client._last_device_info = {
            "controlunit_name": "Old name",
            "order_number": "123456",
        }
        client._last_measurement_attributes = {}
        client._handle_measurement = lambda *_args, **_kwargs: None

        DHEClient._handle_device_info_value(
            client,
            "set:ste.common.version:controlunitName",
            None,
        )
        DHEClient._handle_device_info_value(
            client,
            "set:ste.common.version:orderNumber",
            "   ",
        )

        self.assertNotIn("controlunit_name", client._last_device_info)
        self.assertNotIn("order_number", client._last_device_info)

        DHEClient._handle_device_info_value(
            client,
            "set:ste.common.version:controlunitName",
            "  Bathroom DHE  ",
        )
        DHEClient._handle_device_info_value(
            client,
            "set:ste.common.version:orderNumber",
            "  A-123  ",
        )

        self.assertEqual(client._last_device_info["controlunit_name"], "Bathroom DHE")
        self.assertEqual(client._last_device_info["order_number"], "A-123")

    async def test_set_controlunit_name_writes_assign_command_and_confirms(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._last_device_info = {}
        sent_packets: list[dict[str, object]] = []
        client._message_packet = lambda payload: payload

        async def _post_packet(_ctx: object, packet: dict[str, object]) -> None:
            sent_packets.append(packet)

        client._post_packet = AsyncMock(side_effect=_post_packet)

        async def _request_app_value(_ctx: object, command: str) -> None:
            self.assertEqual(command, "get:ste.common.version:controlunitName")
            client._last_device_info["controlunit_name"] = "Bathroom DHE"

        client._request_app_value = AsyncMock(side_effect=_request_app_value)

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry

        confirmed = await DHEClient.set_controlunit_name(client, "  Bathroom DHE  ")

        self.assertEqual(confirmed, "Bathroom DHE")
        self.assertEqual(
            sent_packets,
            [
                {
                    "command": "assign:ste.common.version:controlunitName",
                    "value": "Bathroom DHE",
                }
            ],
        )
        client._request_app_value.assert_awaited_once()

    async def test_bridge_temperature_maximum_writes_assign_command(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        sent_packets: list[dict[str, object]] = []
        client._message_packet = lambda payload: payload

        async def _post_packet(_ctx: object, packet: dict[str, object]) -> None:
            sent_packets.append(packet)

        client._post_packet = AsyncMock(side_effect=_post_packet)

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry
        client._request_app_value = AsyncMock()

        confirmed = await DHEClient.bridge_temperature_maximum(client)

        self.assertTrue(confirmed)
        self.assertEqual(
            sent_packets,
            [
                {
                    "command": "assign:ste.common.temperature:maxOverride",
                    "value": True,
                }
            ],
        )
        client._request_app_value.assert_not_awaited()

    async def test_web_interface_version_updates_protocol_version(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient
        client = DHEClient.__new__(DHEClient)
        client._last_device_info = {}
        client._last_measurement_attributes = {}
        client._last_measurements = {}
        captured_calls: list[tuple[int, str, bool]] = []

        def _capture_measurement(
            odb_id: int,
            value: str,
            *,
            force_update: bool = False,
        ) -> None:
            captured_calls.append((odb_id, value, force_update))
            client._last_measurements[odb_id] = value

        client._handle_measurement = _capture_measurement

        DHEClient._handle_web_interface_version(client, "1.9.00")
        DHEClient._handle_odb_protocol_version_value(client, 1)

        attributes = client._last_measurement_attributes[protocol_module.ID_DEVICE_INFO]
        self.assertEqual(client._last_device_info["protocol_version"], "1.9.00")
        self.assertEqual(client._last_device_info["raw_odb_protocol_version"], 1)
        self.assertEqual(attributes["protocol_version"], "1.9.00")
        self.assertEqual(attributes["raw_odb_protocol_version"], 1)
        self.assertEqual(
            captured_calls,
            [
                (protocol_module.ID_DEVICE_INFO, "DHE Connect", True),
                (protocol_module.ID_PROTOCOL_VERSION, "1.9.00", True),
                (protocol_module.ID_DEVICE_INFO, "DHE Connect", True),
                (protocol_module.ID_PROTOCOL_VERSION, "1.9.00", False),
            ],
        )

    def test_extract_web_app_version_from_dhe_root_html(self) -> None:
        web_version = _load_component_module("client_web_version")

        self.assertEqual(
            web_version.extract_web_app_version(
                '<html manifest="/manifest-1.9.00.appcache"></html>',
            ),
            "1.9.00",
        )
        self.assertEqual(
            web_version.extract_web_app_version(
                '<script src="assets/ste-dhe-1.9.00.js"></script>',
            ),
            "1.9.00",
        )
        self.assertIsNone(
            web_version.extract_web_app_version(
                '<html manifest="/manifest-secret token.appcache"></html>',
            ),
        )

    async def test_web_interface_version_probe_ignores_decode_failure(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        class _DecodeFailureResponse:
            status = 200

            async def __aenter__(self) -> "_DecodeFailureResponse":
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            async def text(self) -> str:
                raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid")

        class _FakeSession:
            def get(self, _url: str, *, timeout: object) -> _DecodeFailureResponse:
                return _DecodeFailureResponse()

        client = DHEClient.__new__(DHEClient)
        client.base_url = "http://dhe.local:8443"
        client._session = _FakeSession()
        client._last_device_info = {}
        client._last_measurements = {}
        client._handle_web_interface_version = Mock()

        await DHEClient._request_web_interface_version(client)

        client._handle_web_interface_version.assert_not_called()

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
                (cents_id, 29.0),
                (euros_id, 0.0),
            ],
        )

    async def test_set_price_rolls_back_known_components_when_cache_is_partial(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError

        client = DHEClient.__new__(DHEClient)
        euros_id = 100
        cents_id = 101
        client._last_measurements = {euros_id: 2.0}
        calls: list[tuple[int, float]] = []

        async def _write_odb_value(odb_id: int, value):
            calls.append((odb_id, float(value)))
            if (odb_id, float(value)) == (cents_id, 45.0):
                raise DHEError("write failed")
            return float(value)

        client.write_odb_value = AsyncMock(side_effect=_write_odb_value)

        with self.assertRaisesRegex(DHEError, "write failed"):
            await DHEClient._set_price(
                client,
                3.45,
                euros_id,
                cents_id,
                max_value=9.99,
            )

        self.assertEqual(
            calls,
            [
                (euros_id, 3.0),
                (cents_id, 45.0),
                (euros_id, 2.0),
            ],
        )

    async def test_set_price_rolls_back_when_runtime_error_fails_write(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

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
                raise RuntimeError("unexpected invalid state")
            return float(value)

        client.write_odb_value = AsyncMock(side_effect=_write_odb_value)

        with self.assertRaisesRegex(RuntimeError, "unexpected invalid state"):
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
                (cents_id, 29.0),
                (euros_id, 0.0),
            ],
        )

    async def test_set_price_reports_rollback_failure(self) -> None:
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

        async def _write_odb_value(odb_id: int, value):
            if (odb_id, float(value)) == (cents_id, 5.0):
                raise DHEError("write failed")
            if (odb_id, float(value)) == (euros_id, 0.0):
                raise DHEError("rollback failed")
            return float(value)

        client.write_odb_value = AsyncMock(side_effect=_write_odb_value)

        with self.assertRaisesRegex(
            DHEError,
            "write failed; price rollback failed: ODB id 100: rollback failed",
        ):
            await DHEClient._set_price(
                client,
                1.05,
                euros_id,
                cents_id,
                max_value=9.99,
            )

    async def test_set_price_reports_runtime_rollback_failure(self) -> None:
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

        async def _write_odb_value(odb_id: int, value):
            if (odb_id, float(value)) == (cents_id, 5.0):
                raise RuntimeError("unexpected invalid state")
            if (odb_id, float(value)) == (euros_id, 0.0):
                raise RuntimeError("rollback invalid state")
            return float(value)

        client.write_odb_value = AsyncMock(side_effect=_write_odb_value)

        with self.assertRaisesRegex(
            DHEError,
            (
                "unexpected invalid state; price rollback failed: "
                "ODB id 100: rollback invalid state"
            ),
        ):
            await DHEClient._set_price(
                client,
                1.05,
                euros_id,
                cents_id,
                max_value=9.99,
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

            with open(client.token_path, encoding="utf-8") as file:
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

    async def test_set_temperature_memory_existing_slot_without_confirmation_is_rejected(
        self,
    ) -> None:
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

    async def test_set_temperature_memory_requires_generation_change_after_write(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError

        client = DHEClient.__new__(DHEClient)
        client._temperature_memory_generation = 0
        client._last_measurement_attributes = {}
        client._temperature_memory_ids = lambda _slot: (0, 700)

        refresh_calls = 0

        async def _refresh_memory(_ctx: object | None = None) -> None:
            nonlocal refresh_calls
            refresh_calls += 1
            if refresh_calls == 1:
                # Initial pre-write refresh changes generation and caches the slot.
                client._temperature_memory_generation = 1
                client._last_measurement_attributes[700] = {"name": "Dusche"}
            # Second refresh simulates no post-write update from the DHE.

        client._refresh_temperature_memories = AsyncMock(side_effect=_refresh_memory)
        client._temperature_memory_payload = lambda *_args, **_kwargs: {
            "name": "Dusche",
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

        with self.assertRaisesRegex(DHEError, "was not confirmed"):
            await DHEClient.set_temperature_memory(client, 0, 38.0)

        self.assertEqual(refresh_calls, 2)

    async def test_set_temperature_memory_name_without_confirmation_is_rejected(
        self,
    ) -> None:
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

    async def test_set_temperature_memory_name_readback_mismatch_is_rejected(
        self,
    ) -> None:
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

    async def test_timer_duration_update_resets_remaining_like_dhe_ui(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._last_measurements = {}
        client._measurement_callbacks = set()
        client._pending_write_future = None
        client._pending_write_id = None
        client._pending_write_expected = None
        captured_calls: list[tuple[int, object]] = []
        client._measurement_callbacks.add(
            lambda measurement_id, value: captured_calls.append((measurement_id, value))
        )

        DHEClient._handle_app_timer_value(
            client,
            "set:ste.app.brushTimer:durationMilliseconds",
            120000,
        )

        self.assertEqual(
            client._last_measurements[protocol_module.ID_BRUSH_TIMER_DURATION],
            2.0,
        )
        self.assertEqual(
            client._last_measurements[protocol_module.ID_BRUSH_TIMER_REMAINING],
            2.0,
        )
        self.assertEqual(
            captured_calls,
            [
                (protocol_module.ID_BRUSH_TIMER_DURATION, 2.0),
                (protocol_module.ID_BRUSH_TIMER_REMAINING, 2.0),
            ],
        )

    async def test_timer_get_activation_readback_updates_measurement(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        client_types = _load_component_module("client_types")
        DHEClient = client_module.DHEClient
        DHEEvent = client_types.DHEEvent

        client = DHEClient.__new__(DHEClient)
        published: list[tuple[int, object]] = []
        client._diagnostic_callbacks = set()
        client._diagnostic_state = {}
        client._last_measurements = {}
        client._last_measurement_attributes = {}
        client._last_message_monotonic = None
        client._measurement_callbacks = {
            lambda measurement_id, value: published.append((measurement_id, value))
        }
        client._message_count = 0
        client._pending_write_expected = None
        client._pending_write_future = None
        client._pending_write_id = None

        await DHEClient._handle_runtime_event(
            client,
            DHEEvent(
                "message",
                {
                    "command": f"get:{protocol_module.SHOWER_TIMER_PATH}:activation",
                    "value": False,
                },
            ),
        )

        self.assertEqual(
            client._last_measurements[protocol_module.ID_SHOWER_TIMER_ACTIVATION],
            False,
        )
        self.assertEqual(
            published,
            [(protocol_module.ID_SHOWER_TIMER_ACTIVATION, False)],
        )
        self.assertEqual(client._last_runtime_parser_category, "timer_value")

    async def test_timer_reset_restores_remaining_to_configured_duration(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._last_measurements = {
            protocol_module.ID_SHOWER_TIMER_DURATION: 5.0,
            protocol_module.ID_SHOWER_TIMER_REMAINING: 0.0,
            protocol_module.ID_SHOWER_TIMER_ACTIVATION: True,
        }
        client._measurement_callbacks = set()
        client._pending_write_future = None
        client._pending_write_id = None
        client._pending_write_expected = None
        captured_calls: list[tuple[int, object]] = []
        client._measurement_callbacks.add(
            lambda measurement_id, value: captured_calls.append((measurement_id, value))
        )

        DHEClient._handle_app_timer_reset(
            client,
            "set:ste.app.showerTimer:reset",
        )

        self.assertEqual(
            client._last_measurements[protocol_module.ID_SHOWER_TIMER_REMAINING],
            5.0,
        )
        self.assertFalse(
            client._last_measurements[protocol_module.ID_SHOWER_TIMER_ACTIVATION]
        )
        self.assertEqual(
            captured_calls,
            [
                (protocol_module.ID_SHOWER_TIMER_REMAINING, 5.0),
                (protocol_module.ID_SHOWER_TIMER_ACTIVATION, False),
            ],
        )

    async def test_temperature_max_override_runtime_event_updates_diagnostics(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        client_types = _load_component_module("client_types")
        DHEClient = client_module.DHEClient
        DHEEvent = client_types.DHEEvent

        client = DHEClient.__new__(DHEClient)
        client._diagnostic_state = {}
        client._diagnostic_callbacks = set()
        client._last_message_monotonic = None
        client._message_count = 0
        client._runtime_parser_stats = {}
        client._last_runtime_parser_category = None
        client._last_app_values = {}
        client._last_measurements = {}
        client._last_measurement_attributes = {}
        client._last_radio_state = {}
        client._last_radio_stations = []
        client._last_radio_favorites = []
        client._last_radio_catalogs = {
            field: [] for field in protocol_module.RADIO_CATALOG_FIELDS
        }
        client._last_radio_genres = []
        client._radio_catalog_generations = {
            field: 0 for field in protocol_module.RADIO_CATALOG_FIELDS
        }
        client._radio_stations_generation = 0
        client._radio_favorites_generation = 0
        client._radio_genres_generation = 0
        client._radio_callbacks = set()
        client._last_weather_state = {}
        client._last_weather_countries = []
        client._weather_callbacks = set()
        client._weather_search_generation = 0
        client._weather_favorites_generation = 0
        client._weather_countries_generation = 0

        await DHEClient._handle_runtime_event(
            client,
            DHEEvent(
                "message",
                {
                    "command": protocol_module.TEMPERATURE_MAX_OVERRIDE_SET_COMMAND,
                    "value": True,
                },
            ),
        )

        self.assertEqual(
            client._last_app_values[protocol_module.TEMPERATURE_MAX_OVERRIDE_SET_COMMAND],
            True,
        )
        self.assertIs(client._diagnostic_state["temperature_max_override_active"], True)
        self.assertEqual(
            client._diagnostic_state["temperature_max_override_source_command"],
            protocol_module.TEMPERATURE_MAX_OVERRIDE_SET_COMMAND,
        )
        self.assertEqual(client._last_runtime_parser_category, "temperature_max_override")
        self.assertEqual(client._runtime_parser_stats["temperature_max_override"], 1)

    async def test_child_safety_off_does_not_request_temperature_max_override_readback(
        self,
    ) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._last_measurements = {protocol_module.ID_CHILD_SAFETY_ACTIVE: True}
        client._request_app_value = AsyncMock()

        def _handle_measurement(
            odb_id: int,
            value: object,
            *,
            force_update: bool = False,
        ) -> None:
            del force_update
            client._last_measurements[odb_id] = value

        client._handle_measurement = _handle_measurement
        client._update_diagnostics = Mock()

        DHEClient._handle_odb_child_safety_active_value(client, False)

        client._request_app_value.assert_not_awaited()
        client._update_diagnostics.assert_called_once_with(
            child_safety_active=False
        )

    async def test_child_safety_off_updates_diagnostics_when_already_off(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._last_measurements = {protocol_module.ID_CHILD_SAFETY_ACTIVE: False}
        client._request_app_value = AsyncMock()

        def _handle_measurement(
            odb_id: int,
            value: object,
            *,
            force_update: bool = False,
        ) -> None:
            del force_update
            client._last_measurements[odb_id] = value

        client._handle_measurement = _handle_measurement
        client._update_diagnostics = Mock()

        DHEClient._handle_odb_child_safety_active_value(client, False)

        client._request_app_value.assert_not_awaited()
        client._update_diagnostics.assert_called_once_with(
            child_safety_active=False
        )

    async def test_shower_timer_writes_use_shower_timer_path(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._last_measurements = {protocol_module.ID_SHOWER_TIMER_DURATION: 5.0}
        client._write_app_value = AsyncMock(side_effect=[5.0, False, 5.0])
        client._handle_measurement = Mock()

        duration = await DHEClient.set_shower_timer_duration_minutes(client, 5.0)
        activation = await DHEClient.set_shower_timer_activation(client, False)
        reset = await DHEClient.reset_shower_timer(client)

        self.assertEqual(duration, 5.0)
        self.assertFalse(activation)
        self.assertTrue(reset)
        self.assertEqual(
            client._write_app_value.await_args_list[0].args,
            (
                "assign:ste.app.showerTimer:durationMilliseconds",
                300000,
                protocol_module.ID_SHOWER_TIMER_DURATION,
                5.0,
            ),
        )
        self.assertEqual(
            client._write_app_value.await_args_list[1].args,
            (
                "assign:ste.app.showerTimer:activation",
                False,
                protocol_module.ID_SHOWER_TIMER_ACTIVATION,
                False,
            ),
        )
        self.assertEqual(
            client._write_app_value.await_args_list[2].args,
            (
                "assign:ste.app.showerTimer:reset",
                True,
                protocol_module.ID_SHOWER_TIMER_REMAINING,
                5.0,
            ),
        )
        client._handle_measurement.assert_any_call(
            protocol_module.ID_SHOWER_TIMER_REMAINING,
            5.0,
            force_update=True,
        )
        client._handle_measurement.assert_any_call(
            protocol_module.ID_SHOWER_TIMER_ACTIVATION,
            False,
            force_update=True,
        )

    async def test_brush_timer_writes_keep_brush_timer_path(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._last_measurements = {protocol_module.ID_BRUSH_TIMER_DURATION: 4.0}
        client._write_app_value = AsyncMock(side_effect=[4.0, True, 4.0])
        client._handle_measurement = Mock()

        duration = await DHEClient.set_brush_timer_duration_minutes(client, 4.0)
        activation = await DHEClient.set_brush_timer_activation(client, True)
        reset = await DHEClient.reset_brush_timer(client)

        self.assertEqual(duration, 4.0)
        self.assertTrue(activation)
        self.assertTrue(reset)
        self.assertEqual(
            client._write_app_value.await_args_list[0].args,
            (
                "assign:ste.app.brushTimer:durationMilliseconds",
                240000,
                protocol_module.ID_BRUSH_TIMER_DURATION,
                4.0,
            ),
        )
        self.assertEqual(
            client._write_app_value.await_args_list[1].args,
            (
                "assign:ste.app.brushTimer:activation",
                True,
                protocol_module.ID_BRUSH_TIMER_ACTIVATION,
                True,
            ),
        )
        self.assertEqual(
            client._write_app_value.await_args_list[2].args,
            (
                "assign:ste.app.brushTimer:reset",
                True,
                protocol_module.ID_BRUSH_TIMER_REMAINING,
                4.0,
            ),
        )
        client._handle_measurement.assert_any_call(
            protocol_module.ID_BRUSH_TIMER_REMAINING,
            4.0,
            force_update=True,
        )
        client._handle_measurement.assert_any_call(
            protocol_module.ID_BRUSH_TIMER_ACTIVATION,
            False,
            force_update=True,
        )

    def test_repeated_none_measurements_are_deduped(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._last_measurements = {}
        client._measurement_callbacks = set()
        client._pending_write_future = None
        client._pending_write_id = None
        client._pending_write_expected = None
        client._notify_callbacks = Mock()

        DHEClient._handle_measurement(client, 123, None)
        DHEClient._handle_measurement(client, 123, None)
        DHEClient._handle_measurement(client, 123, None, force_update=True)

        self.assertEqual(client._notify_callbacks.call_count, 2)

    async def test_open_session_uses_structured_open_payload(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._get_text = AsyncMock(
            return_value=(
                '0{"sid":"polling sid","websocketSid":"websocket sid",'
                '"pingInterval":15000}'
            )
        )
        client._post_packet = AsyncMock(return_value="")
        client._poll_url = Mock(return_value="http://example.invalid/socket.io")

        ctx = await DHEClient._open_session(client, "token value")

        self.assertEqual(ctx.sid, "polling sid")
        self.assertEqual(ctx.websocket_sid, "websocket sid")
        self.assertEqual(ctx.url_token, "token value")
        self.assertEqual(ctx.ping_interval, 15.0)
        client._post_packet.assert_awaited_once_with(ctx, f"40/{protocol_module.NS}")

    def test_parse_socketio_events_continues_after_malformed_frame(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        client = DHEClient.__new__(DHEClient)

        events = DHEClient._parse_socketio_events(
            client,
            [
                '42/1.0.0,["message",{"text":"bad",}]'
                '42/1.0.0,["message",{"command":"ok","value":1}]',
            ],
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].name, "message")
        self.assertEqual(events[0].data, {"command": "ok", "value": 1})

    async def test_websocket_upgrade_leaves_control_ping_handling_enabled(self) -> None:
        client_module = _load_client()
        transport_module = _load_component_module("client_transport")
        DHEClient = client_module.DHEClient
        DHESession = client_module.DHESession

        message = types.SimpleNamespace(
            type=transport_module.aiohttp.WSMsgType.TEXT,
            data="3probe",
        )

        class _FakeWebSocket:
            closed = False

            def __init__(self) -> None:
                self.send_str = AsyncMock()
                self.close = AsyncMock()
                self.receive = AsyncMock(return_value=message)

        websocket = _FakeWebSocket()
        session = types.SimpleNamespace(ws_connect=AsyncMock(return_value=websocket))
        client = DHEClient.__new__(DHEClient)
        client._session = session
        client._send_lock = client_module.asyncio.Lock()
        client._websocket_url_candidates = Mock(
            return_value=(("websocket-sid", "socket-sid", "ws://example.invalid/ws"),)
        )
        client._websocket_headers = Mock(
            return_value={"Origin": "http://example.invalid"}
        )

        def _capture_background_task(coro, _name):
            coro.close()
            return object()

        client._create_background_task = Mock(side_effect=_capture_background_task)

        ctx = DHESession(url_token="token", sid="sid")

        await DHEClient._upgrade_to_websocket(client, ctx)

        self.assertIs(ctx.websocket, websocket)
        self.assertIsNotNone(ctx.websocket_ping_task)
        session.ws_connect.assert_awaited_once()
        kwargs = session.ws_connect.await_args.kwargs
        self.assertTrue(kwargs["autoping"])
        self.assertIsNone(kwargs["heartbeat"])
        websocket.send_str.assert_any_await("2probe")
        websocket.send_str.assert_any_await("5")

    async def test_websocket_upgrade_failure_updates_transport_metrics(self) -> None:
        client_module = _load_client()
        transport_module = _load_component_module("client_transport")
        DHEClient = client_module.DHEClient
        DHESession = client_module.DHESession

        session = types.SimpleNamespace(
            ws_connect=AsyncMock(
                side_effect=transport_module.aiohttp.ClientError("connect failed")
            )
        )
        client = DHEClient.__new__(DHEClient)
        client._session = session
        client._websocket_upgrade_failures = 0
        client._websocket_url_candidates = Mock(
            return_value=(("websocket-sid", "socket-sid", "ws://example.invalid/ws"),)
        )
        client._websocket_headers = Mock(
            return_value={"Origin": "http://example.invalid"}
        )
        ctx = DHESession(url_token="token", sid="sid")

        with self.assertRaisesRegex(client_module.DHEError, "ClientError"):
            await DHEClient._upgrade_to_websocket(client, ctx)

        self.assertEqual(client.transport_statistics["websocket_upgrade_failures"], 1)

    async def test_websocket_heartbeat_failure_forces_reconnect(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHESession = client_module.DHESession

        websocket = types.SimpleNamespace(closed=False)
        client = DHEClient.__new__(DHEClient)
        client._stopped = client_module.asyncio.Event()
        client._send_websocket_packet = AsyncMock(
            side_effect=RuntimeError("socket write failed")
        )
        client._force_reconnect = AsyncMock()
        ctx = DHESession(
            url_token="token",
            sid="sid",
            websocket=websocket,
            ping_interval=0,
        )

        await DHEClient._websocket_ping_loop(client, ctx)

        client._send_websocket_packet.assert_awaited_once_with(ctx, "2")
        client._force_reconnect.assert_awaited_once()
        args, kwargs = client._force_reconnect.await_args
        self.assertEqual(args, (ctx,))
        self.assertNotIn("immediate_availability", kwargs)
        self.assertEqual(
            kwargs["reason"],
            "Heartbeat failed: RuntimeError: socket write failed",
        )

    async def test_websocket_idle_timeout_returns_closed_event(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHESession = client_module.DHESession
        transport_module = sys.modules[f"{PACKAGE_NAME}.client_transport"]
        original_min_timeout = transport_module.WEBSOCKET_IDLE_TIMEOUT_MIN
        transport_module.WEBSOCKET_IDLE_TIMEOUT_MIN = 0.1

        class _IdleWebSocket:
            closed = False

            async def receive(self):
                await asyncio.sleep(1)

        client = DHEClient.__new__(DHEClient)
        ctx = DHESession(
            url_token="token",
            sid="sid",
            websocket=_IdleWebSocket(),
            ping_interval=0.01,
        )

        try:
            events = await DHEClient._read_websocket_events_once(client, ctx)
        finally:
            transport_module.WEBSOCKET_IDLE_TIMEOUT_MIN = original_min_timeout

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].name, "__closed")
        self.assertEqual(events[0].data, "DHE websocket idle timeout after 0.1s")

    async def test_force_reconnect_keeps_available_inside_reconnect_grace(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._ctx = None
        client._ready = client_module.asyncio.Event()
        client._ready.set()
        client._stopped = client_module.asyncio.Event()
        client._online = True
        client._available = True
        client._online_callbacks = set()
        client._availability_callbacks = set()
        client._diagnostic_callbacks = set()
        client._diagnostic_state = {}
        client._last_message_monotonic = None
        client._notify_callbacks = Mock()
        client._reconnect_grace_task = None
        scheduled_tasks: list[tuple[object, str]] = []

        def _capture_background_task(coro, name):
            scheduled_tasks.append((coro, name))
            coro.close()
            return types.SimpleNamespace(done=lambda: False, cancel=Mock())

        client._create_background_task = Mock(side_effect=_capture_background_task)
        client._connection_supervisor = client_module.DHEConnectionSupervisor(
            base_delay=2.0,
            max_delay=10.0,
            grace_period=15.0,
            monotonic=lambda: 0.0,
        )

        await DHEClient._force_reconnect(client, reason="test reconnect")

        self.assertFalse(client._ready.is_set())
        self.assertFalse(client._online)
        self.assertTrue(client._available)
        self.assertEqual(client._diagnostic_state["connection_state"], "reconnecting")
        self.assertEqual(
            client._diagnostic_state["last_reconnect_reason"], "test reconnect"
        )
        self.assertEqual(client._diagnostic_state["next_reconnect_delay_seconds"], 2.0)
        self.assertEqual(
            scheduled_tasks[0][1],
            "stiebel_dhe_connect_reconnect_grace_expiry",
        )

    async def test_force_reconnect_marks_unavailable_after_reconnect_grace(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        now = 0.0

        client = DHEClient.__new__(DHEClient)
        client._ctx = None
        client._ready = client_module.asyncio.Event()
        client._ready.set()
        client._stopped = client_module.asyncio.Event()
        client._online = True
        client._available = True
        client._online_callbacks = set()
        client._availability_callbacks = set()
        client._diagnostic_callbacks = set()
        client._diagnostic_state = {}
        client._last_message_monotonic = None
        client._notify_callbacks = Mock()
        client._reconnect_grace_task = None
        scheduled_task = types.SimpleNamespace(done=lambda: False, cancel=Mock())

        def _capture_background_task(coro, _name):
            coro.close()
            return scheduled_task

        client._create_background_task = Mock(side_effect=_capture_background_task)
        client._connection_supervisor = client_module.DHEConnectionSupervisor(
            base_delay=2.0,
            max_delay=10.0,
            grace_period=15.0,
            monotonic=lambda: now,
        )

        await DHEClient._force_reconnect(client, reason="first reconnect")
        self.assertTrue(client._available)

        now = 16.0
        client._online = True
        client._ready.set()
        await DHEClient._force_reconnect(client, reason="second reconnect")

        self.assertFalse(client._available)
        scheduled_task.cancel.assert_called_once()
        self.assertEqual(client._diagnostic_state["connection_state"], "reconnecting")
        self.assertEqual(
            client._diagnostic_state["last_reconnect_reason"], "second reconnect"
        )
        self.assertEqual(client._diagnostic_state["next_reconnect_delay_seconds"], 4.0)

    async def test_reconnect_grace_timer_marks_unavailable_when_expired(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        now = 0.0

        diagnostic_callback = Mock()
        client = DHEClient.__new__(DHEClient)
        client._ctx = None
        client._ready = client_module.asyncio.Event()
        client._stopped = client_module.asyncio.Event()
        client._available = True
        client._availability_callbacks = set()
        client._diagnostic_callbacks = {diagnostic_callback}
        client._copy_diagnostic_state = Mock(
            return_value={"connection_state": "reconnecting"}
        )
        client._notify_callbacks = Mock()
        client._reconnect_grace_task = object()
        client._connection_supervisor = client_module.DHEConnectionSupervisor(
            grace_period=15.0,
            monotonic=lambda: now,
        )
        client._connection_supervisor.mark_disconnected()

        now = 15.1
        client._reconnect_grace_task = client_module.asyncio.current_task()
        await DHEClient._expire_reconnect_grace_after(client, 0)

        self.assertFalse(client._available)
        self.assertIsNone(client._reconnect_grace_task)
        self.assertTrue(
            any(
                call.args and call.args[0] == "diagnostic"
                for call in client._notify_callbacks.call_args_list
            )
        )

    async def test_stale_reconnect_grace_timer_does_not_clear_new_timer(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        now = 15.1
        new_task = object()

        client = DHEClient.__new__(DHEClient)
        client._ctx = None
        client._ready = client_module.asyncio.Event()
        client._stopped = client_module.asyncio.Event()
        client._available = True
        client._availability_callbacks = set()
        client._notify_callbacks = Mock()
        client._reconnect_grace_task = new_task
        client._connection_supervisor = client_module.DHEConnectionSupervisor(
            grace_period=15.0,
            monotonic=lambda: now,
        )
        client._connection_supervisor.mark_disconnected()

        await DHEClient._expire_reconnect_grace_after(client, 0)

        self.assertIs(client._reconnect_grace_task, new_task)

    async def test_websocket_heartbeat_does_not_hide_programming_runtime_errors(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHESession = client_module.DHESession

        websocket = types.SimpleNamespace(closed=False)
        client = DHEClient.__new__(DHEClient)
        client._stopped = client_module.asyncio.Event()
        client._send_websocket_packet = AsyncMock(
            side_effect=RuntimeError("unexpected invalid state")
        )
        client._force_reconnect = AsyncMock()
        ctx = DHESession(
            url_token="token",
            sid="sid",
            websocket=websocket,
            ping_interval=0,
        )

        with self.assertRaisesRegex(RuntimeError, "unexpected invalid state"):
            await DHEClient._websocket_ping_loop(client, ctx)

        client._send_websocket_packet.assert_awaited_once_with(ctx, "2")
        client._force_reconnect.assert_not_awaited()

    async def test_initial_values_reread_nominal_power_on_each_session(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient
        DHESession = client_module.DHESession

        client = DHEClient.__new__(DHEClient)
        client._last_measurements = {protocol_module.ID_NOMINAL_POWER: 18.0}
        client._request_odb_value = AsyncMock()
        client._request_app_value = AsyncMock()
        client._request_optional_odb_value = AsyncMock()
        client._request_optional_app_value = AsyncMock()
        client._request_web_interface_version = AsyncMock()
        ctx = DHESession(url_token="token", sid="sid")

        await DHEClient._request_initial_values(client, ctx)

        requested_odb_ids = [
            call.args[1] for call in client._request_odb_value.await_args_list
        ]
        requested_app_commands = [
            call.args[1] for call in client._request_app_value.await_args_list
        ]
        self.assertEqual(requested_odb_ids, list(protocol_module.INITIAL_VALUE_IDS))
        self.assertEqual(requested_odb_ids.count(protocol_module.ID_NOMINAL_POWER), 1)
        self.assertEqual(
            requested_app_commands[: len(protocol_module.APP_TIMER_REQUEST_COMMANDS)],
            list(protocol_module.APP_TIMER_REQUEST_COMMANDS),
        )
        client._request_web_interface_version.assert_awaited_once_with()

    async def test_runtime_measurement_refresh_requests_one_odb_or_app_value(
        self,
    ) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient
        DHESession = client_module.DHESession

        client = DHEClient.__new__(DHEClient)
        ctx = DHESession(url_token="token", sid="sid")

        async def _run_without_retry(_message, operation, *, timeout=45.0):
            self.assertEqual(timeout, 10.0)
            return await operation(ctx)

        client._run_command_without_reconnect_retry = _run_without_retry
        client._request_odb_value = AsyncMock()
        client._request_app_value = AsyncMock()
        client._request_web_interface_version = AsyncMock()

        await DHEClient.request_measurement_refresh(
            client,
            odb_id=protocol_module.ID_ODB_HOT_WATER_VOLUME,
        )
        await DHEClient.request_measurement_refresh(
            client,
            app_command="get:ste.app.showerTimer:remainingMilliseconds",
        )

        client._request_odb_value.assert_awaited_once_with(
            ctx,
            protocol_module.ID_ODB_HOT_WATER_VOLUME,
        )
        client._request_app_value.assert_awaited_once_with(
            ctx,
            "get:ste.app.showerTimer:remainingMilliseconds",
        )

        await DHEClient.request_measurement_refresh(
            client,
            odb_id=protocol_module.ID_PROTOCOL_VERSION,
        )
        client._request_web_interface_version.assert_awaited_once_with()

    async def test_app_read_source_matches_get_request_to_set_readback(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._pending_app_read_deadlines = {}

        DHEClient._mark_app_read_requested(client, "get:ste.app.radio:station")

        self.assertTrue(
            DHEClient._app_read_source(client, "set:ste.app.radio:station")
        )
        self.assertFalse(
            DHEClient._app_read_source(client, "set:ste.app.radio:station")
        )

    async def test_runtime_measurement_refresh_tracks_only_radio_app_readbacks(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHESession = client_module.DHESession

        client = DHEClient.__new__(DHEClient)
        ctx = DHESession(url_token="token", sid="sid")
        client._pending_app_read_deadlines = {}
        client._post_packet = AsyncMock()
        client._message_packet = lambda payload: str(payload)

        await DHEClient._request_app_value(
            client,
            ctx,
            "get:ste.app.weather:location",
        )
        await DHEClient._request_app_value(
            client,
            ctx,
            "get:ste.app.radio:station",
        )

        self.assertNotIn(
            "get:ste.app.weather:location",
            client._pending_app_read_deadlines,
        )
        self.assertIn(
            "get:ste.app.radio:station",
            client._pending_app_read_deadlines,
        )

    async def test_runtime_radio_station_readback_does_not_infer_playing(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._last_app_values = {}
        client._last_radio_state = {}
        client._last_radio_favorites = []
        client._radio_favorites_generation = 0
        states: list[dict[str, object]] = []
        client._radio_callbacks = {states.append}

        DHEClient._handle_radio_value(
            client,
            "set:ste.app.radio:station",
            {"Id": 166, "Name": "Radio Test"},
            requested_readback=True,
        )

        self.assertEqual(client._last_radio_state["station"]["Id"], 166)
        self.assertNotIn("play", client._last_radio_state)
        self.assertEqual(states[-1]["station"]["Id"], 166)

    async def test_runtime_radio_device_station_update_does_not_infer_playing(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._last_app_values = {}
        client._last_radio_state = {}
        client._last_radio_favorites = []
        client._radio_favorites_generation = 0
        states: list[dict[str, object]] = []
        client._radio_callbacks = {states.append}

        DHEClient._handle_radio_value(
            client,
            "set:ste.app.radio:station",
            {"Id": 166, "Name": "Radio Test"},
        )

        self.assertNotIn("play", client._last_radio_state)
        self.assertNotIn("play", states[-1])
        self.assertEqual(client._last_radio_state["station"]["Id"], 166)
        self.assertEqual(states[-1]["station"]["Id"], 166)

    async def test_runtime_radio_device_title_update_does_not_infer_playing(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._last_app_values = {}
        client._last_radio_state = {"play": False}
        client._last_radio_favorites = []
        client._radio_favorites_generation = 0
        states: list[dict[str, object]] = []
        client._radio_callbacks = {states.append}

        DHEClient._handle_radio_value(
            client,
            "set:ste.app.radio:title",
            "Now Playing",
        )

        self.assertIs(client._last_radio_state["play"], False)
        self.assertIs(states[-1]["play"], False)
        self.assertEqual(client._last_radio_state["title"], "Now Playing")
        self.assertEqual(states[-1]["title"], "Now Playing")

    async def test_runtime_ignores_unknown_radio_and_bad_weather_payloads(
        self,
    ) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient
        client_types = sys.modules[f"{PACKAGE_NAME}.client_types"]

        client = DHEClient.__new__(DHEClient)
        client._diagnostic_state = {}
        client._diagnostic_callbacks = set()
        client._last_message_monotonic = None
        client._message_count = 0
        client._runtime_parser_stats = {}
        client._last_runtime_parser_category = None
        client._last_app_values = {}
        client._last_radio_state = {}
        client._last_radio_stations = []
        client._last_radio_favorites = []
        client._last_radio_catalogs = {
            field: [] for field in protocol_module.RADIO_CATALOG_FIELDS
        }
        client._last_radio_genres = []
        client._radio_catalog_generations = {
            field: 0 for field in protocol_module.RADIO_CATALOG_FIELDS
        }
        client._radio_stations_generation = 0
        client._radio_favorites_generation = 0
        client._radio_genres_generation = 0
        client._radio_callbacks = set()
        client._last_weather_state = {}
        client._last_weather_countries = []
        client._weather_callbacks = set()
        client._weather_search_generation = 0
        client._weather_favorites_generation = 0
        client._weather_countries_generation = 0

        await DHEClient._handle_runtime_event(
            client,
            client_types.DHEEvent(
                "message",
                {
                    "command": "set:ste.app.radio:unknownRuntimeField",
                    "value": {"unexpected": "shape"},
                },
            ),
        )
        await DHEClient._handle_runtime_event(
            client,
            client_types.DHEEvent(
                "message",
                {
                    "command": protocol_module.WEATHER_FORECAST_SET_COMMAND,
                    "value": "not-a-weather-list",
                },
            ),
        )

        self.assertEqual(client._last_radio_state, {})
        self.assertEqual(client._last_weather_state, {})
        self.assertEqual(client._runtime_parser_stats["radio_unhandled"], 1)
        self.assertEqual(client._runtime_parser_stats["weather_state"], 1)
        self.assertIn(
            protocol_module.WEATHER_FORECAST_SET_COMMAND,
            client._last_app_values,
        )

    def test_invalid_known_odb_readbacks_are_ignored(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._odb_value_handlers = {}
        client._handle_measurement = Mock()

        for odb_id, raw_value in (
            (protocol_module.ID_ODB_HEATING_ENERGY, "12,5"),
            (protocol_module.ID_ODB_HOT_WATER_VOLUME, "42"),
            (protocol_module.ID_ODB_POSSIBLE_ENERGY_SAVING, "7"),
            (protocol_module.ID_ODB_ACTUAL_WATER_SAVING, "15"),
        ):
            DHEClient._handle_odb_value(
                client,
                odb_id,
                raw_value,
                is_valid=False,
            )

        client._handle_measurement.assert_not_called()

    def test_invalid_odb_readback_records_diagnostic_error_name(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        diagnostic_updates: list[dict[str, object]] = []
        client._diagnostic_callbacks = {diagnostic_updates.append}
        client._diagnostic_state = {}
        client._handle_measurement = Mock()
        client._last_message_monotonic = None
        client._odb_value_handlers = {}

        DHEClient._handle_odb_value(
            client,
            protocol_module.ID_WATER_FLOW,
            999,
            is_valid=False,
            error_code=3,
        )

        client._handle_measurement.assert_not_called()
        self.assertEqual(client._runtime_parser_stats["invalid_odb_readback"], 1)
        self.assertEqual(
            client._diagnostic_state["last_invalid_odb"],
            {
                "id": protocol_module.ID_WATER_FLOW,
                "name": "ODB_Is_VS",
                "value": 999,
                "is_valid": False,
                "error_code": 3,
                "error_name": "ODB_ERR_MAX_LIMIT",
            },
        )
        self.assertTrue(client._diagnostic_state["last_invalid_odb_at"])
        self.assertEqual(
            diagnostic_updates[-1]["last_invalid_odb"]["error_name"],
            "ODB_ERR_MAX_LIMIT",
        )

    def test_requested_zero_diagnostic_odb_readbacks_are_ignored(self) -> None:
        client_module = _load_client()
        client_types = _load_component_module("client_types")
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._odb_value_handlers = {}
        client._handle_measurement = Mock()

        for odb_id in protocol_module.ODB_ZERO_REQUEST_READBACK_IGNORE_IDS:
            DHEClient._handle_odb_value(
                client,
                odb_id,
                "0",
                source=client_types.ODB_READ_SOURCE_REQUESTED,
            )

        client._handle_measurement.assert_not_called()

    def test_spontaneous_zero_diagnostic_odb_updates_are_published(self) -> None:
        client_module = _load_client()
        client_types = _load_component_module("client_types")
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._odb_value_handlers = {}
        client._handle_measurement = Mock()

        for odb_id in protocol_module.ODB_ZERO_REQUEST_READBACK_IGNORE_IDS:
            DHEClient._handle_odb_value(
                client,
                odb_id,
                "0",
                source=client_types.ODB_READ_SOURCE_RUNTIME,
            )

        self.assertEqual(
            client._handle_measurement.call_count,
            len(protocol_module.ODB_ZERO_REQUEST_READBACK_IGNORE_IDS),
        )
        for call in client._handle_measurement.call_args_list:
            self.assertEqual(call.args[1], 0.0)

    def test_requested_nonzero_diagnostic_odb_readbacks_are_published(self) -> None:
        client_module = _load_client()
        client_types = _load_component_module("client_types")
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._odb_value_handlers = {}
        client._handle_measurement = Mock()

        DHEClient._handle_odb_value(
            client,
            protocol_module.ID_ODB_HOT_WATER_VOLUME,
            "10",
            source=client_types.ODB_READ_SOURCE_REQUESTED,
        )

        client._handle_measurement.assert_called_once_with(
            protocol_module.ID_ODB_HOT_WATER_VOLUME,
            1.0,
            force_update=True,
        )

    async def test_get_odb_readback_forces_regular_startup_measurement_update(
        self,
    ) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        client_types = _load_component_module("client_types")
        DHEClient = client_module.DHEClient
        DHEEvent = client_types.DHEEvent

        client = DHEClient.__new__(DHEClient)
        published: list[tuple[int, object]] = []
        client._diagnostic_callbacks = set()
        client._diagnostic_state = {}
        client._last_measurements = {protocol_module.ID_WATER_FLOW: 0.0}
        client._last_measurement_attributes = {}
        client._last_message_monotonic = None
        client._measurement_callbacks = {
            lambda odb_id, value: published.append((odb_id, value))
        }
        client._message_count = 0
        client._pending_odb_read_deadlines = {}
        client._pending_write_expected = None
        client._pending_write_future = None
        client._pending_write_id = None
        client._odb_value_handlers = {
            protocol_module.ID_WATER_FLOW: (
                DHEClient._handle_odb_water_flow_value.__get__(client, DHEClient)
            ),
        }

        DHEClient._mark_odb_read_requested(client, protocol_module.ID_WATER_FLOW)
        await DHEClient._handle_runtime_event(
            client,
            DHEEvent(
                "message",
                {
                    "command": protocol_module.ODB_GET_COMMAND,
                    "value": {
                        "id": protocol_module.ID_WATER_FLOW,
                        "value": 0,
                        "isValid": True,
                    },
                },
            ),
        )

        self.assertEqual(published, [(protocol_module.ID_WATER_FLOW, 0.0)])
        self.assertEqual(client._last_runtime_parser_category, "odb_value")
        self.assertEqual(client._runtime_parser_stats["odb_value"], 1)

    async def test_named_odb_payload_id_updates_matching_measurement(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        client_types = _load_component_module("client_types")
        DHEClient = client_module.DHEClient
        DHEEvent = client_types.DHEEvent

        client = DHEClient.__new__(DHEClient)
        published: list[tuple[int, object]] = []
        client._diagnostic_callbacks = set()
        client._diagnostic_state = {}
        client._last_measurements = {}
        client._last_measurement_attributes = {}
        client._last_message_monotonic = None
        client._measurement_callbacks = {
            lambda odb_id, value: published.append((odb_id, value))
        }
        client._message_count = 0
        client._pending_odb_read_deadlines = {}
        client._pending_write_expected = None
        client._pending_write_future = None
        client._pending_write_id = None
        client._odb_value_handlers = {
            protocol_module.ID_WATER_FLOW: (
                DHEClient._handle_odb_water_flow_value.__get__(client, DHEClient)
            ),
        }

        await DHEClient._handle_runtime_event(
            client,
            DHEEvent(
                "message",
                {
                    "command": protocol_module.ODB_SET_COMMAND,
                    "value": {"id": "ODB_Is_VS", "value": 27, "isValid": True},
                },
            ),
        )

        self.assertEqual(published, [(protocol_module.ID_WATER_FLOW, 2.7)])
        self.assertEqual(client._last_measurements[protocol_module.ID_WATER_FLOW], 2.7)
        self.assertEqual(client._runtime_parser_stats["odb_value"], 1)

    async def test_invalid_odb_runtime_payload_normalizes_error_debug_name(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        client_types = _load_component_module("client_types")
        DHEClient = client_module.DHEClient
        DHEEvent = client_types.DHEEvent

        client = DHEClient.__new__(DHEClient)
        client._diagnostic_callbacks = set()
        client._diagnostic_state = {}
        client._handle_measurement = Mock()
        client._last_message_monotonic = None
        client._message_count = 0
        client._pending_odb_read_deadlines = {}
        client._odb_value_handlers = {}

        await DHEClient._handle_runtime_event(
            client,
            DHEEvent(
                "message",
                {
                    "command": protocol_module.ODB_GET_COMMAND,
                    "value": {
                        "id": "ODB_Is_VS",
                        "value": 999,
                        "isValid": False,
                        "errorCode": "ODB_ERR_MAX_LIMIT",
                    },
                },
            ),
        )

        client._handle_measurement.assert_not_called()
        self.assertEqual(client._runtime_parser_stats["odb_value"], 1)
        self.assertEqual(client._runtime_parser_stats["invalid_odb_readback"], 1)
        self.assertEqual(
            client._diagnostic_state["last_invalid_odb"]["error_name"],
            "ODB_ERR_MAX_LIMIT",
        )

    async def test_named_odb_command_suffix_updates_matching_measurement(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        client_types = _load_component_module("client_types")
        DHEClient = client_module.DHEClient
        DHEEvent = client_types.DHEEvent

        client = DHEClient.__new__(DHEClient)
        published: list[tuple[int, object]] = []
        client._diagnostic_callbacks = set()
        client._diagnostic_state = {}
        client._last_measurements = {}
        client._last_measurement_attributes = {}
        client._last_message_monotonic = None
        client._measurement_callbacks = {
            lambda odb_id, value: published.append((odb_id, value))
        }
        client._message_count = 0
        client._pending_odb_read_deadlines = {}
        client._pending_write_expected = None
        client._pending_write_future = None
        client._pending_write_id = None
        client._odb_value_handlers = {
            protocol_module.ID_WATER_FLOW: (
                DHEClient._handle_odb_water_flow_value.__get__(client, DHEClient)
            ),
        }

        await DHEClient._handle_runtime_event(
            client,
            DHEEvent(
                "message",
                {
                    "command": "set:ste.common.odb:ODB_Is_VS",
                    "value": 31,
                },
            ),
        )

        self.assertEqual(published, [(protocol_module.ID_WATER_FLOW, 3.1)])
        self.assertEqual(client._last_measurements[protocol_module.ID_WATER_FLOW], 3.1)
        self.assertEqual(client._runtime_parser_stats["odb_value"], 1)

    async def test_requested_zero_diagnostic_get_readbacks_are_still_ignored(
        self,
    ) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        client_types = _load_component_module("client_types")
        DHEClient = client_module.DHEClient
        DHEEvent = client_types.DHEEvent

        client = DHEClient.__new__(DHEClient)
        client._diagnostic_callbacks = set()
        client._diagnostic_state = {}
        client._handle_measurement = Mock()
        client._last_message_monotonic = None
        client._message_count = 0
        client._pending_odb_read_deadlines = {}
        client._odb_value_handlers = {}

        odb_id = protocol_module.ID_ODB_HOT_WATER_VOLUME
        DHEClient._mark_odb_read_requested(client, odb_id)
        await DHEClient._handle_runtime_event(
            client,
            DHEEvent(
                "message",
                {
                    "command": protocol_module.ODB_GET_COMMAND,
                    "value": {"id": odb_id, "value": 0, "isValid": True},
                },
            ),
        )

        client._handle_measurement.assert_not_called()
        self.assertEqual(client._runtime_parser_stats["odb_value"], 1)

    async def test_pending_diagnostic_zero_set_updates_remain_runtime_updates(
        self,
    ) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        client_types = _load_component_module("client_types")
        DHEClient = client_module.DHEClient
        DHEEvent = client_types.DHEEvent

        client = DHEClient.__new__(DHEClient)
        client._diagnostic_callbacks = set()
        client._diagnostic_state = {}
        client._handle_measurement = Mock()
        client._last_message_monotonic = None
        client._message_count = 0
        client._pending_odb_read_deadlines = {}
        client._odb_value_handlers = {}

        odb_id = protocol_module.ID_ODB_HOT_WATER_VOLUME
        DHEClient._mark_odb_read_requested(client, odb_id)
        await DHEClient._handle_runtime_event(
            client,
            DHEEvent(
                "message",
                {
                    "command": protocol_module.ODB_SET_COMMAND,
                    "value": {"id": odb_id, "value": 0, "isValid": True},
                },
            ),
        )

        client._handle_measurement.assert_called_once_with(
            odb_id,
            0.0,
            force_update=False,
        )
        self.assertTrue(DHEClient._consume_odb_read_request(client, odb_id))
        self.assertEqual(client._runtime_parser_stats["odb_value"], 1)

    def test_odb_read_request_tracking_expires_after_one_response(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._pending_odb_read_deadlines = {}

        DHEClient._mark_odb_read_requested(
            client,
            protocol_module.ID_WATER_FLOW,
        )
        self.assertTrue(
            DHEClient._consume_odb_read_request(
                client,
                protocol_module.ID_WATER_FLOW,
            )
        )
        self.assertFalse(
            DHEClient._consume_odb_read_request(
                client,
                protocol_module.ID_WATER_FLOW,
            )
        )

        DHEClient._mark_odb_read_requested(
            client,
            protocol_module.ID_ODB_HOT_WATER_VOLUME,
        )

        self.assertTrue(
            DHEClient._consume_odb_read_request(
                client,
                protocol_module.ID_ODB_HOT_WATER_VOLUME,
            )
        )
        self.assertFalse(
            DHEClient._consume_odb_read_request(
                client,
                protocol_module.ID_ODB_HOT_WATER_VOLUME,
            )
        )

        client._pending_odb_read_deadlines[protocol_module.ID_ODB_HOT_WATER_VOLUME] = (
            0.0
        )
        self.assertFalse(
            DHEClient._consume_odb_read_request(
                client,
                protocol_module.ID_ODB_HOT_WATER_VOLUME,
            )
        )


if __name__ == "__main__":
    unittest.main()
