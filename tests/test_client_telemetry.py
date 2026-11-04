"""Focused DHE client regression tests."""

from __future__ import annotations

import types
import unittest
from typing import Self
from unittest.mock import AsyncMock, Mock

from tests.client_test_support import (
    _load_client,
    _load_component_module,
    _load_protocol,
)


class TestClientTelemetry(unittest.IsolatedAsyncioTestCase):
    async def test_malformed_numeric_telegram_does_not_block_valid_update(self) -> None:
        module = _load_client()
        module.async_get_clientsession = Mock(return_value=object())
        client = module.DHEClient(types.SimpleNamespace(), "example.invalid", 8443, None, "Test")
        for value in ("1e309", "nan", "-inf", 10**400):
            client._handle_odb_value(33, value)
            self.assertNotIn(33, client.last_measurements)
        client._handle_odb_value(33, 1)
        self.assertIn(33, client.last_measurements)


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
            headers = {}
            content_length = 1

            @property
            def content(self):
                return self

            async def __aenter__(self) -> Self:
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            async def iter_chunked(self, _size):
                yield b"\xff"

        class _FakeSession:
            def get(self, _url: str, **kwargs) -> _DecodeFailureResponse:
                return _DecodeFailureResponse()

        client = DHEClient.__new__(DHEClient)
        client.base_url = "http://dhe.local:8443"
        client._session = _FakeSession()
        client._last_device_info = {}
        client._last_measurements = {}
        client._handle_web_interface_version = Mock()

        await DHEClient._request_web_interface_version(client)

        client._handle_web_interface_version.assert_not_called()


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
