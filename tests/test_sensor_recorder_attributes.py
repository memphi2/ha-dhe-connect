"""Tests for recorder attribute exclusions on sensor entities."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import types
import sys
import time
import unittest
from unittest.mock import AsyncMock, patch

try:
    from tests.test_aiohttp_stubs import _ensure_aiohttp_stub
except ModuleNotFoundError:
    from test_aiohttp_stubs import _ensure_aiohttp_stub

ROOT = Path(__file__).resolve().parents[1]
COMPONENT_DIR = ROOT / "custom_components" / "stiebel_dhe_connect"
PACKAGE_NAME = "custom_components.stiebel_dhe_connect"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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


def _load_sensor_module():
    _load_component_module("client_mapping")
    _load_component_module("client")
    _load_component_module("entity_helpers")
    _load_component_module("entity_state_helpers")
    _load_component_module("runtime_helpers")
    return _load_component_module("sensor")


def _fake_error_status_client():
    return types.SimpleNamespace(
        host="127.0.0.1",
        port=8443,
        device_identifier=None,
        online=True,
        available=True,
        last_setpoint=38.0,
        last_measurements={},
    )


class TestSensorRecorderAttributes(unittest.TestCase):
    """Validate unrecorded dynamic attributes for recorder safety."""

    def test_stiebel_sensor_excludes_heavy_dynamic_attributes(self) -> None:
        sensor_module = _load_sensor_module()
        attributes = sensor_module.StiebelDHESensor._unrecorded_attributes

        self.assertIn("chart", attributes)
        self.assertIn("possible", attributes)
        self.assertIn("real", attributes)
        self.assertIn("consumption", attributes)
        self.assertIn("activation_rate", attributes)

    def test_water_and_energy_device_classes_use_valid_state_classes(self) -> None:
        sensor_module = _load_sensor_module()
        descriptions = {
            item.key: item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.device_class
            in {
                sensor_module.SensorDeviceClass.WATER,
                sensor_module.SensorDeviceClass.ENERGY,
            }
        }
        valid_state_classes = {
            None,
            sensor_module.SensorStateClass.TOTAL,
            sensor_module.SensorStateClass.TOTAL_INCREASING,
        }

        self.assertEqual(
            descriptions["odb_possible_energy_saving"].state_class,
            sensor_module.SensorStateClass.TOTAL,
        )
        self.assertEqual(
            descriptions["odb_actual_water_saving"].state_class,
            sensor_module.SensorStateClass.TOTAL,
        )
        for key in (
            "water_consumption_week",
            "water_consumption_year",
            "water_consumption_total",
            "energy_consumption_week",
            "energy_consumption_year",
            "energy_consumption_total",
            "odb_hot_water_volume",
            "odb_heating_energy",
        ):
            self.assertEqual(
                descriptions[key].state_class,
                sensor_module.SensorStateClass.TOTAL_INCREASING,
            )
            self.assertTrue(descriptions[key].keep_last_value_when_unavailable)
        self.assertNotIn(
            sensor_module.SensorStateClass.MEASUREMENT,
            {item.state_class for item in descriptions.values()},
        )
        self.assertTrue(
            all(item.state_class in valid_state_classes for item in descriptions.values())
        )

    def test_scald_protection_limit_uses_visible_icon(self) -> None:
        sensor_module = _load_sensor_module()
        description = next(
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.key == "scald_protection_temperature_limit"
        )

        self.assertEqual(description.icon, "mdi:thermometer-alert")

    def test_wellness_runtime_sensor_maps_odb_32(self) -> None:
        sensor_module = _load_sensor_module()
        protocol_module = _load_component_module("protocol")
        description = next(
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.key == "wellness_runtime_normalized"
        )

        self.assertEqual(
            description.odb_id,
            protocol_module.ID_WELLNESS_TIME_NORMALIZED,
        )
        self.assertEqual(
            description.native_unit_of_measurement,
            sensor_module.UnitOfTime.SECONDS,
        )
        self.assertEqual(
            description.device_class,
            sensor_module.SensorDeviceClass.DURATION,
        )
        self.assertIsNone(description.state_class)
        self.assertEqual(
            description.entity_category,
            sensor_module.EntityCategory.DIAGNOSTIC,
        )
        self.assertFalse(description.entity_registry_enabled_default)

    def test_wellness_runtime_sensor_writes_live_updates(self) -> None:
        sensor_module = _load_sensor_module()
        protocol_module = _load_component_module("protocol")
        description = next(
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.key == "wellness_runtime_normalized"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None
            online = True
            last_measurement_attributes = {}

        sensor = sensor_module.StiebelDHESensor(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
            description=description,
        )
        writes: list[float | str | None] = []
        sensor.async_write_ha_state = lambda: writes.append(sensor._attr_native_value)

        sensor._handle_measurement_update(
            protocol_module.ID_WELLNESS_TIME_NORMALIZED,
            57.3,
        )

        self.assertEqual(sensor._attr_native_value, 57.3)
        self.assertTrue(sensor._attr_available)
        self.assertEqual(writes, [57.3])

    def test_attribute_key_sensors_do_not_duplicate_device_info_attributes(self) -> None:
        sensor_module = _load_sensor_module()
        description = next(
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.key == "product_id"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None
            online = True
            last_measurement_attributes = {
                description.odb_id: {
                    "device_id": "234467-private-tail",
                    "device_type": "DHE Connect",
                    "wlan_mac": "AA-BB-CC-DD-EE-FF",
                    "bluetooth_mac": "11:22:33:44:55:66",
                }
            }

        sensor = sensor_module.StiebelDHESensor(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
            description=description,
        )
        writes: list[str | None] = []
        sensor.async_write_ha_state = lambda: writes.append(sensor._attr_native_value)

        sensor._handle_measurement_update(description.odb_id, "DHE Connect")

        self.assertEqual(sensor._attr_native_value, "234467-private-tail")
        self.assertEqual(
            sensor._attr_extra_state_attributes,
            {"source_command": "set:ste.common.version:gadgetData"},
        )
        self.assertEqual(writes, ["234467-private-tail"])

    def test_error_status_sensor_excludes_dynamic_inlet_attributes(self) -> None:
        sensor_module = _load_sensor_module()
        attributes = sensor_module.StiebelDHEErrorStatusSensor._unrecorded_attributes

        self.assertIn("inlet_temperature", attributes)
        self.assertIn("inlet_minus_setpoint", attributes)

    def test_diagnostic_sensor_skips_volatile_message_updates(self) -> None:
        sensor_module = _load_sensor_module()
        description = next(
            item
            for item in sensor_module.DIAGNOSTIC_SENSOR_DESCRIPTIONS
            if item.key == "connection_state"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None

        sensor = sensor_module.StiebelDHEDiagnosticSensor(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
            description=description,
        )
        writes: list[str | int | None] = []
        sensor.async_write_ha_state = lambda: writes.append(sensor._attr_native_value)

        sensor._handle_diagnostic_update(
            {
                "connection_state": "connected",
                "session_id": "sid-1",
                "last_message_age_seconds": 0,
                "last_message_command": "set:ste.common.odb:value",
                "last_message_received_at": "2026-05-16T12:00:00Z",
                "last_message_summary": {"id": 13, "value": 21.0},
                "last_invalid_odb": {
                    "id": 15,
                    "name": "ODB_Is_VS",
                    "error_name": "ODB_ERR_MAX_LIMIT",
                },
                "last_invalid_odb_at": "2026-05-16T12:00:00Z",
                "message_count": 1,
                "next_reconnect_delay_seconds": 2.0,
            }
        )
        sensor._handle_diagnostic_update(
            {
                "connection_state": "connected",
                "session_id": "sid-1",
                "last_message_age_seconds": 1,
                "last_message_command": "set:ste.app.consumption:waterYears",
                "last_message_received_at": "2026-05-16T12:00:01Z",
                "last_message_summary": {"id": 14, "value": 38.0},
                "last_invalid_odb": {
                    "id": 15,
                    "name": "ODB_Is_VS",
                    "error_name": "ODB_ERR_MIN_LIMIT",
                },
                "last_invalid_odb_at": "2026-05-16T12:00:01Z",
                "message_count": 2,
                "next_reconnect_delay_seconds": 4.0,
            }
        )

        self.assertEqual(writes, ["connected"])
        self.assertEqual(sensor._attr_extra_state_attributes, {"session_id": "sid-1"})

        sensor._handle_diagnostic_update(
            {
                "connection_state": "connected",
                "session_id": "sid-2",
                "last_message_received_at": "2026-05-16T12:00:02Z",
            }
        )

        self.assertEqual(writes, ["connected", "connected"])
        self.assertEqual(sensor._attr_extra_state_attributes, {"session_id": "sid-2"})

    def test_next_reconnect_delay_diagnostic_accepts_float_state(self) -> None:
        sensor_module = _load_sensor_module()
        description = next(
            item
            for item in sensor_module.DIAGNOSTIC_SENSOR_DESCRIPTIONS
            if item.key == "next_reconnect_delay"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None

        sensor = sensor_module.StiebelDHEDiagnosticSensor(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
            description=description,
        )
        sensor.async_write_ha_state = lambda: None

        sensor._handle_diagnostic_update(
            {
                "connection_state": "reconnecting",
                "next_reconnect_delay_seconds": 2.5,
            }
        )

        self.assertEqual(sensor._attr_native_value, 2.5)
        self.assertTrue(sensor._attr_available)
        self.assertEqual(
            sensor._attr_extra_state_attributes,
            {"connection_state": "reconnecting"},
        )

    def test_next_reconnect_delay_diagnostic_defaults_to_zero(self) -> None:
        sensor_module = _load_sensor_module()
        description = next(
            item
            for item in sensor_module.DIAGNOSTIC_SENSOR_DESCRIPTIONS
            if item.key == "next_reconnect_delay"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None
            reconnect_count = 0

        sensor = sensor_module.StiebelDHEDiagnosticSensor(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
            description=description,
        )

        sensor._apply_diagnostic_state({"connection_state": "connected"})

        self.assertEqual(sensor._attr_native_value, 0)
        self.assertTrue(sensor._attr_available)

    def test_flow_and_power_write_filters_use_stricter_thresholds(self) -> None:
        sensor_module = _load_sensor_module()
        self.assertIn("water_flow", sensor_module.DEFAULT_ENABLED_SENSOR_KEYS)
        self.assertIn("power", sensor_module.DEFAULT_ENABLED_SENSOR_KEYS)
        self.assertIn("inlet_temperature", sensor_module.DEFAULT_ENABLED_SENSOR_KEYS)
        self.assertIn("outlet_temperature", sensor_module.DEFAULT_ENABLED_SENSOR_KEYS)
        self.assertIn("device_status", sensor_module.DEFAULT_ENABLED_SENSOR_KEYS)
        water_flow_description = next(
            item for item in sensor_module.SENSOR_DESCRIPTIONS if item.key == "water_flow"
        )
        self.assertEqual(water_flow_description.suggested_display_precision, 1)
        self.assertEqual(sensor_module.SENSOR_WRITE_FILTERS["water_flow"], (0.2, 45.0))
        self.assertEqual(sensor_module.SENSOR_WRITE_FILTERS["power"], (0.2, 45.0))
        self.assertEqual(
            sensor_module.SENSOR_WRITE_FILTERS["water_consumption_total"],
            (0.001, 60.0),
        )
        self.assertEqual(
            sensor_module.SENSOR_WRITE_FILTERS["energy_consumption_total"],
            (0.05, 60.0),
        )
        self.assertEqual(
            sensor_module.SENSOR_WRITE_FILTERS["saving_monitor_consumption_water"],
            (0.25, 60.0),
        )
        self.assertEqual(
            sensor_module.SENSOR_WRITE_FILTERS["saving_monitor_activation_rate"],
            (1.0, 120.0),
        )
        self.assertIn("chart", sensor_module.StiebelDHESensor._unrecorded_attributes)
        self.assertIn("possible", sensor_module.StiebelDHESensor._unrecorded_attributes)

    def test_live_timer_and_fill_sensors_are_not_write_filtered(self) -> None:
        sensor_module = _load_sensor_module()

        self.assertNotIn("bath_fill_remaining_volume", sensor_module.SENSOR_WRITE_FILTERS)
        self.assertNotIn("bath_fill_current_volume", sensor_module.SENSOR_WRITE_FILTERS)
        self.assertNotIn("brush_timer_remaining", sensor_module.SENSOR_WRITE_FILTERS)
        self.assertNotIn("shower_timer_remaining", sensor_module.SENSOR_WRITE_FILTERS)

    def test_timer_remaining_counts_down_locally_while_active(self) -> None:
        sensor_module = _load_sensor_module()
        protocol_module = _load_component_module("protocol")
        description = next(
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.key == "brush_timer_remaining"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None
            online = True
            last_measurements: dict[int, object] = {}
            last_measurement_attributes: dict[int, dict[str, object]] = {}

        sensor = sensor_module.StiebelDHESensor(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
            description=description,
        )
        writes: list[str | float | None] = []
        sensor.async_write_ha_state = lambda: writes.append(sensor._attr_native_value)

        with patch.object(sensor_module.time, "monotonic", return_value=100.0):
            sensor._handle_measurement_update(
                protocol_module.ID_BRUSH_TIMER_REMAINING,
                121.0 / 60.0,
            )
        with patch.object(sensor_module.time, "monotonic", return_value=101.0):
            sensor._handle_measurement_update(
                protocol_module.ID_BRUSH_TIMER_ACTIVATION,
                True,
            )
        with patch.object(sensor_module.time, "monotonic", return_value=108.0):
            sensor._write_timer_countdown_state()

        self.assertTrue(sensor._timer_active)
        self.assertEqual(sensor._attr_native_value, "1:54")
        self.assertEqual(writes, ["2:01", "1:54"])

    def test_timer_remaining_freezes_current_value_when_deactivated(self) -> None:
        sensor_module = _load_sensor_module()
        protocol_module = _load_component_module("protocol")
        description = next(
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.key == "shower_timer_remaining"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None
            online = True
            last_measurements: dict[int, object] = {}
            last_measurement_attributes: dict[int, dict[str, object]] = {}

        sensor = sensor_module.StiebelDHESensor(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
            description=description,
        )
        writes: list[str | float | None] = []
        sensor.async_write_ha_state = lambda: writes.append(sensor._attr_native_value)

        with patch.object(sensor_module.time, "monotonic", return_value=10.0):
            sensor._handle_measurement_update(
                protocol_module.ID_SHOWER_TIMER_REMAINING,
                1.0,
            )
            sensor._handle_measurement_update(
                protocol_module.ID_SHOWER_TIMER_ACTIVATION,
                True,
            )
        with patch.object(sensor_module.time, "monotonic", return_value=20.0):
            sensor._handle_measurement_update(
                protocol_module.ID_SHOWER_TIMER_ACTIVATION,
                False,
            )
        with patch.object(sensor_module.time, "monotonic", return_value=40.0):
            sensor._write_timer_countdown_state()

        self.assertFalse(sensor._timer_active)
        self.assertEqual(sensor._attr_native_value, "0:50")
        self.assertEqual(writes, ["1:00", "0:50"])

    def test_timer_stop_refreshes_remaining_from_dhe_even_when_value_exists(self) -> None:
        sensor_module = _load_sensor_module()
        protocol_module = _load_component_module("protocol")
        description = next(
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.key == "shower_timer_remaining"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None
            online = True
            last_measurements: dict[int, object] = {}
            last_measurement_attributes: dict[int, dict[str, object]] = {}

            def __init__(self) -> None:
                self.request_measurement_refresh = AsyncMock()

        class _FakeHass:
            def __init__(self) -> None:
                self.tasks = []

            def async_create_task(self, coro, *, name: str | None = None):
                task = asyncio.create_task(coro, name=name)
                self.tasks.append(task)
                return task

        async def _run() -> _FakeClient:
            client = _FakeClient()
            hass = _FakeHass()
            sensor = sensor_module.StiebelDHESensor(
                entry_id="test-entry",
                name="Test DHE",
                client=client,
                description=description,
            )
            sensor.hass = hass
            sensor.async_on_remove = lambda _callback: None
            sensor.async_write_ha_state = lambda: None

            with patch.object(sensor_module.time, "monotonic", return_value=10.0):
                sensor._handle_measurement_update(
                    protocol_module.ID_SHOWER_TIMER_REMAINING,
                    1.0,
                )
                sensor._handle_measurement_update(
                    protocol_module.ID_SHOWER_TIMER_ACTIVATION,
                    True,
                )
            with patch.object(sensor_module.time, "monotonic", return_value=20.0):
                sensor._handle_measurement_update(
                    protocol_module.ID_SHOWER_TIMER_ACTIVATION,
                    False,
                )
            await asyncio.gather(*hass.tasks, return_exceptions=True)
            return client

        client = asyncio.run(_run())

        client.request_measurement_refresh.assert_awaited_once_with(
            odb_id=protocol_module.ID_SHOWER_TIMER_REMAINING,
            app_command="get:ste.app.showerTimer:remainingMilliseconds",
        )

    def test_timer_reactivation_restarts_cancelled_countdown_task(self) -> None:
        sensor_module = _load_sensor_module()
        protocol_module = _load_component_module("protocol")
        description = next(
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.key == "brush_timer_remaining"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None
            online = True
            last_measurements: dict[int, object] = {}
            last_measurement_attributes: dict[int, dict[str, object]] = {}

            def __init__(self) -> None:
                self.request_measurement_refresh = AsyncMock()

        class _FakeHass:
            def __init__(self) -> None:
                self.tasks: list[asyncio.Task[object]] = []

            def async_create_task(self, coro, *, name: str | None = None):
                task = asyncio.create_task(coro, name=name)
                self.tasks.append(task)
                return task

        async def _run() -> list[asyncio.Task[object]]:
            client = _FakeClient()
            hass = _FakeHass()
            sensor = sensor_module.StiebelDHESensor(
                entry_id="test-entry",
                name="Test DHE",
                client=client,
                description=description,
            )
            sensor.hass = hass
            sensor.async_on_remove = lambda _callback: None
            sensor.async_write_ha_state = lambda: None

            with patch.object(sensor_module.time, "monotonic", return_value=10.0):
                sensor._handle_measurement_update(
                    protocol_module.ID_BRUSH_TIMER_REMAINING,
                    1.0,
                )
                sensor._handle_measurement_update(
                    protocol_module.ID_BRUSH_TIMER_ACTIVATION,
                    True,
                )
            first_task = sensor._timer_countdown_task
            with patch.object(sensor_module.time, "monotonic", return_value=11.0):
                sensor._handle_measurement_update(
                    protocol_module.ID_BRUSH_TIMER_ACTIVATION,
                    False,
                )
                sensor._handle_measurement_update(
                    protocol_module.ID_BRUSH_TIMER_ACTIVATION,
                    True,
                )
            second_task = sensor._timer_countdown_task
            self.assertIsNotNone(first_task)
            self.assertIsNotNone(second_task)
            self.assertIsNot(first_task, second_task)
            self.assertGreater(first_task.cancelling(), 0)
            self.assertIn(second_task, hass.tasks)
            sensor._timer_active = False
            sensor._cancel_timer_countdown()
            await asyncio.gather(*hass.tasks, return_exceptions=True)
            return hass.tasks

        tasks = asyncio.run(_run())

        self.assertGreaterEqual(len(tasks), 2)

    def test_timer_remaining_resets_to_duration_when_expired(self) -> None:
        sensor_module = _load_sensor_module()
        protocol_module = _load_component_module("protocol")
        description = next(
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.key == "brush_timer_remaining"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None
            online = True
            last_measurements = {
                protocol_module.ID_BRUSH_TIMER_DURATION: 3.0,
            }
            last_measurement_attributes: dict[int, dict[str, object]] = {}

        sensor = sensor_module.StiebelDHESensor(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
            description=description,
        )
        writes: list[str | float | None] = []
        sensor.async_write_ha_state = lambda: writes.append(sensor._attr_native_value)

        with patch.object(sensor_module.time, "monotonic", return_value=10.0):
            sensor._handle_measurement_update(
                protocol_module.ID_BRUSH_TIMER_REMAINING,
                1.0 / 60.0,
            )
            sensor._handle_measurement_update(
                protocol_module.ID_BRUSH_TIMER_ACTIVATION,
                True,
            )
        with patch.object(sensor_module.time, "monotonic", return_value=12.0):
            sensor._handle_measurement_update(
                protocol_module.ID_BRUSH_TIMER_ACTIVATION,
                False,
            )

        self.assertFalse(sensor._timer_active)
        self.assertEqual(sensor._attr_native_value, "3:00")
        self.assertEqual(writes, ["0:01", "3:00"])

    def test_flow_filter_blocks_tiny_jitter_but_allows_visible_delta_or_interval(self) -> None:
        sensor_module = _load_sensor_module()
        description = next(
            item for item in sensor_module.SENSOR_DESCRIPTIONS if item.key == "water_flow"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None

        sensor = sensor_module.StiebelDHESensor(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
            description=description,
        )
        sensor._last_written_native_value = 5.0
        sensor._last_written_monotonic = time.monotonic()

        self.assertFalse(sensor._should_write_measurement_state(5.19))
        self.assertTrue(sensor._should_write_measurement_state(5.21))

        sensor._last_written_native_value = 5.0
        sensor._last_written_monotonic = -1_000_000_000.0
        self.assertTrue(sensor._should_write_measurement_state(5.19))

    def test_numeric_write_filters_always_publish_zero_boundary_crossings(self) -> None:
        sensor_module = _load_sensor_module()
        descriptions = {item.key: item for item in sensor_module.SENSOR_DESCRIPTIONS}

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None

        for key, (min_write_delta, _max_interval) in sensor_module.SENSOR_WRITE_FILTERS.items():
            with self.subTest(key=key):
                description = descriptions[key]
                sensor = sensor_module.StiebelDHESensor(
                    entry_id="test-entry",
                    name="Test DHE",
                    client=_FakeClient(),
                    description=description,
                )
                small_value = min_write_delta / 2
                sensor._last_written_monotonic = time.monotonic()

                sensor._last_written_native_value = 0.0
                self.assertTrue(sensor._should_write_measurement_state(small_value))

                sensor._last_written_native_value = small_value
                self.assertTrue(sensor._should_write_measurement_state(0.0))

                sensor._last_written_native_value = small_value
                self.assertFalse(
                    sensor._should_write_measurement_state(
                        small_value + min_write_delta / 4,
                    )
                )

    def test_power_and_flow_write_runtime_zero_transitions_immediately(self) -> None:
        sensor_module = _load_sensor_module()
        protocol_module = _load_component_module("protocol")
        descriptions = {item.key: item for item in sensor_module.SENSOR_DESCRIPTIONS}

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None
            available = True
            online = True

            def __init__(self) -> None:
                self.last_measurement_attributes: dict[int, dict[str, object]] = {}

        client = _FakeClient()
        power_sensor = sensor_module.StiebelDHESensor(
            entry_id="test-entry",
            name="Test DHE",
            client=client,
            description=descriptions["power"],
        )
        flow_sensor = sensor_module.StiebelDHESensor(
            entry_id="test-entry",
            name="Test DHE",
            client=client,
            description=descriptions["water_flow"],
        )
        power_writes: list[float | str | None] = []
        flow_writes: list[float | str | None] = []
        power_sensor.async_write_ha_state = lambda: power_writes.append(
            power_sensor._attr_native_value
        )
        flow_sensor.async_write_ha_state = lambda: flow_writes.append(
            flow_sensor._attr_native_value
        )
        power_sensor._last_written_native_value = 1.2
        power_sensor._last_written_monotonic = time.monotonic()
        power_sensor._last_written_recorded_attributes = (
            power_sensor._recorded_state_attributes()
        )
        flow_sensor._last_written_native_value = 0.0
        flow_sensor._last_written_monotonic = time.monotonic()
        flow_sensor._last_written_recorded_attributes = (
            flow_sensor._recorded_state_attributes()
        )

        power_sensor._handle_measurement_update(protocol_module.ID_POWER_PERCENT, 0.0)
        flow_sensor._handle_measurement_update(protocol_module.ID_WATER_FLOW, 0.8)

        self.assertEqual(power_writes, [0.0])
        self.assertEqual(flow_writes, [0.8])

    def test_power_and_flow_write_visible_nonzero_delta(self) -> None:
        sensor_module = _load_sensor_module()
        descriptions = {item.key: item for item in sensor_module.SENSOR_DESCRIPTIONS}

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None

        for key in ("power", "water_flow"):
            with self.subTest(key=key):
                sensor = sensor_module.StiebelDHESensor(
                    entry_id="test-entry",
                    name="Test DHE",
                    client=_FakeClient(),
                    description=descriptions[key],
                )
                sensor._last_written_native_value = 1.2
                sensor._last_written_monotonic = time.monotonic()

                self.assertFalse(sensor._should_write_measurement_state(1.39))
                self.assertTrue(sensor._should_write_measurement_state(1.41))

    def test_sensor_refresh_command_uses_timer_or_source_command(self) -> None:
        sensor_module = _load_sensor_module()
        shower_description = next(
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.key == "shower_timer_remaining"
        )
        consumption_description = next(
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.key == "water_consumption_total"
        )
        derived_description = next(
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.key == "bath_fill_remaining_volume"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None

        shower_sensor = sensor_module.StiebelDHESensor(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
            description=shower_description,
        )
        consumption_sensor = sensor_module.StiebelDHESensor(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
            description=consumption_description,
        )
        derived_sensor = sensor_module.StiebelDHESensor(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
            description=derived_description,
        )

        self.assertEqual(
            shower_sensor._refresh_app_command(),
            "get:ste.app.showerTimer:remainingMilliseconds",
        )
        self.assertEqual(
            consumption_sensor._refresh_app_command(),
            "get:ste.app.consumption:waterYears",
        )
        self.assertIsNone(derived_sensor._refresh_app_command())

    def test_missing_sensor_refresh_requests_current_value(self) -> None:
        sensor_module = _load_sensor_module()
        protocol_module = _load_component_module("protocol")
        description = next(
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.key == "shower_timer_remaining"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None

            def __init__(self) -> None:
                self.request_measurement_refresh = AsyncMock()

        client = _FakeClient()
        sensor = sensor_module.StiebelDHESensor(
            entry_id="test-entry",
            name="Test DHE",
            client=client,
            description=description,
        )

        asyncio.run(sensor._async_refresh_missing_measurement())

        client.request_measurement_refresh.assert_awaited_once_with(
            odb_id=protocol_module.ID_SHOWER_TIMER_REMAINING,
            app_command="get:ste.app.showerTimer:remainingMilliseconds",
        )

    def test_zero_guarded_diagnostic_sensors_stay_available_without_value(self) -> None:
        sensor_module = _load_sensor_module()
        protocol_module = _load_component_module("protocol")
        descriptions = [
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.odb_id in protocol_module.ODB_ZERO_REQUEST_READBACK_IGNORE_IDS
        ]

        self.assertEqual(
            {item.key for item in descriptions},
            {
                "odb_heating_energy",
                "odb_hot_water_volume",
                "odb_possible_energy_saving",
                "odb_actual_water_saving",
                "wellness_runtime_normalized",
            },
        )
        self.assertTrue(all(item.available_without_value for item in descriptions))

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None
            online = True

        for description in descriptions:
            sensor = sensor_module.StiebelDHESensor(
                entry_id="test-entry",
                name="Test DHE",
                client=_FakeClient(),
                description=description,
            )

            self.assertTrue(sensor._available_from_value(True, None))
            self.assertFalse(sensor._available_from_value(False, None))

    def test_zero_guarded_diagnostic_sensor_writes_unknown_when_online(self) -> None:
        sensor_module = _load_sensor_module()
        descriptions = tuple(
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.key
            in {
                "odb_heating_energy",
                "odb_hot_water_volume",
                "odb_possible_energy_saving",
                "odb_actual_water_saving",
            }
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None
            online = True
            last_measurements: dict[int, object] = {}
            last_measurement_attributes: dict[int, dict[str, object]] = {}

            def __init__(self) -> None:
                self.request_measurement_refresh = AsyncMock()

            def add_measurement_callback(self, _callback, *, replay=True):
                return lambda: None

            def add_availability_callback(self, _callback):
                return lambda: None

        class _FakeHass:
            def __init__(self) -> None:
                self.tasks = []

            def async_create_task(self, coro, *, name: str | None = None):
                task = asyncio.create_task(coro, name=name)
                self.tasks.append(task)
                return task

        async def _run(description) -> tuple[object, list[bool], _FakeClient, _FakeHass]:
            client = _FakeClient()
            hass = _FakeHass()
            sensor = sensor_module.StiebelDHESensor(
                entry_id="test-entry",
                name="Test DHE",
                client=client,
                description=description,
            )
            writes: list[bool] = []
            sensor.hass = hass
            sensor.async_on_remove = lambda _remove: None
            sensor.async_write_ha_state = lambda: writes.append(sensor._attr_available)

            await sensor.async_added_to_hass()
            if hass.tasks:
                await asyncio.gather(*hass.tasks)
            return sensor, writes, client, hass

        self.assertEqual(len(descriptions), 4)
        for description in descriptions:
            with self.subTest(key=description.key):
                sensor, writes, client, hass = asyncio.run(_run(description))

                self.assertTrue(sensor._attr_available)
                self.assertIsNone(sensor._attr_native_value)
                self.assertEqual(writes, [True])
                self.assertEqual(len(hass.tasks), 1)
                client.request_measurement_refresh.assert_awaited_once_with(
                    odb_id=description.odb_id,
                    app_command=None,
                )

    def test_wellness_runtime_sensor_starts_from_zero_when_online_without_value(self) -> None:
        sensor_module = _load_sensor_module()
        description = next(
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.key == "wellness_runtime_normalized"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None
            online = True
            last_measurements: dict[int, object] = {}
            last_measurement_attributes: dict[int, dict[str, object]] = {}

            def __init__(self) -> None:
                self.request_measurement_refresh = AsyncMock()

            def add_measurement_callback(self, _callback, *, replay=True):
                return lambda: None

            def add_availability_callback(self, _callback):
                return lambda: None

            def add_online_callback(self, _callback):
                return lambda: None

        class _FakeHass:
            def __init__(self) -> None:
                self.tasks = []

            def async_create_task(self, coro, *, name: str | None = None):
                task = asyncio.create_task(coro, name=name)
                self.tasks.append(task)
                return task

        async def _run() -> tuple[object, list[object], _FakeClient]:
            client = _FakeClient()
            hass = _FakeHass()
            sensor = sensor_module.StiebelDHESensor(
                entry_id="test-entry",
                name="Test DHE",
                client=client,
                description=description,
            )
            writes: list[object] = []
            sensor.hass = hass
            sensor.async_on_remove = lambda _remove: None
            sensor.async_write_ha_state = lambda: writes.append(sensor._attr_native_value)

            await sensor.async_added_to_hass()
            if hass.tasks:
                await asyncio.gather(*hass.tasks)
            return sensor, writes, client

        sensor, writes, client = asyncio.run(_run())
        self.assertTrue(sensor._attr_available)
        self.assertEqual(sensor._attr_native_value, 0.0)
        self.assertEqual(writes, [0.0])
        client.request_measurement_refresh.assert_not_awaited()

    def test_zero_guarded_sensor_online_transition_sets_unknown_availability(self) -> None:
        sensor_module = _load_sensor_module()
        description = next(
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.key == "odb_heating_energy"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None
            online = False
            last_measurement_attributes: dict[int, dict[str, object]] = {}

        sensor = sensor_module.StiebelDHESensor(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
            description=description,
        )
        sensor._attr_native_value = None
        sensor._attr_available = False
        writes: list[bool] = []
        sensor.async_write_ha_state = lambda: writes.append(sensor._attr_available)

        sensor._handle_online_update(True)
        sensor._handle_online_update(False)

        self.assertEqual(writes, [True, False])

    def test_wellness_runtime_online_transition_sets_zero_when_missing(self) -> None:
        sensor_module = _load_sensor_module()
        description = next(
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.key == "wellness_runtime_normalized"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None
            online = False
            last_measurement_attributes: dict[int, dict[str, object]] = {}

        sensor = sensor_module.StiebelDHESensor(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
            description=description,
        )
        sensor._attr_native_value = None
        sensor._attr_available = False
        writes: list[tuple[object, bool]] = []
        sensor.async_write_ha_state = lambda: writes.append(
            (sensor._attr_native_value, sensor._attr_available)
        )

        sensor._handle_online_update(True)

        self.assertEqual(sensor._attr_native_value, 0.0)
        self.assertTrue(sensor._attr_available)
        self.assertEqual(writes[-1], (0.0, True))

    def test_missing_sensor_refresh_runs_when_client_comes_online(self) -> None:
        sensor_module = _load_sensor_module()
        protocol_module = _load_component_module("protocol")
        description = next(
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.key == "shower_timer_remaining"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None
            online = False
            last_measurements: dict[int, object] = {}
            last_measurement_attributes: dict[int, dict[str, object]] = {}

            def __init__(self) -> None:
                self.release_refresh = asyncio.Event()
                self.request_measurement_refresh = AsyncMock(
                    side_effect=self._request_measurement_refresh,
                )

            async def _request_measurement_refresh(self, **_kwargs) -> None:
                await self.release_refresh.wait()

            def add_measurement_callback(self, _callback, *, replay=True):
                return lambda: None

            def add_availability_callback(self, _callback):
                return lambda: None

        class _FakeHass:
            def __init__(self) -> None:
                self.tasks = []

            def async_create_task(self, coro, *, name: str | None = None):
                task = asyncio.create_task(coro, name=name)
                self.tasks.append(task)
                return task

        async def _run() -> tuple[_FakeClient, _FakeHass, list[object]]:
            client = _FakeClient()
            hass = _FakeHass()
            removers: list[object] = []
            sensor = sensor_module.StiebelDHESensor(
                entry_id="test-entry",
                name="Test DHE",
                client=client,
                description=description,
            )
            sensor.hass = hass
            sensor.async_on_remove = removers.append
            sensor.async_write_ha_state = lambda: None

            await sensor.async_added_to_hass()
            self.assertEqual(hass.tasks, [])
            remover_count_after_add = len(removers)

            client.online = True
            sensor._handle_availability_update(True)
            sensor._handle_availability_update(True)
            self.assertEqual(len(hass.tasks), 1)
            self.assertEqual(len(removers), remover_count_after_add + 1)

            client.release_refresh.set()
            await asyncio.gather(*hass.tasks)
            return client, hass, removers

        client, _hass, _removers = asyncio.run(_run())

        client.request_measurement_refresh.assert_awaited_once_with(
            odb_id=protocol_module.ID_SHOWER_TIMER_REMAINING,
            app_command="get:ste.app.showerTimer:remainingMilliseconds",
        )

    def test_availability_update_writes_only_on_effective_sensor_change(self) -> None:
        sensor_module = _load_sensor_module()
        description = next(
            item for item in sensor_module.SENSOR_DESCRIPTIONS if item.key == "water_flow"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None

        sensor = sensor_module.StiebelDHESensor(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
            description=description,
        )
        writes: list[bool] = []
        sensor.async_write_ha_state = lambda: writes.append(sensor._attr_available)
        sensor._attr_native_value = 5.0
        sensor._attr_available = True

        sensor._handle_availability_update(True)
        sensor._handle_availability_update(False)
        sensor._handle_availability_update(False)
        sensor._handle_availability_update(True)

        self.assertEqual(writes, [False, True])

    def test_consumption_filter_blocks_small_jitter_but_allows_interval(self) -> None:
        sensor_module = _load_sensor_module()
        description = next(
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.key == "energy_consumption_total"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None

        sensor = sensor_module.StiebelDHESensor(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
            description=description,
        )
        sensor._last_written_native_value = 10.0
        sensor._last_written_monotonic = time.monotonic()

        self.assertFalse(sensor._should_write_measurement_state(10.01))
        self.assertTrue(sensor._should_write_measurement_state(10.05))

        sensor._last_written_native_value = 10.0
        sensor._last_written_monotonic = -1_000_000_000.0
        self.assertTrue(sensor._should_write_measurement_state(10.01))

    def test_total_consumption_sensor_keeps_last_value_when_unavailable(self) -> None:
        sensor_module = _load_sensor_module()
        description = next(
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.key == "energy_consumption_total"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None
            online = True
            last_measurement_attributes: dict[int, dict[str, object]] = {}

        sensor = sensor_module.StiebelDHESensor(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
            description=description,
        )
        writes: list[float | str | None] = []
        sensor.async_write_ha_state = lambda: writes.append(sensor._attr_native_value)
        sensor._attr_native_value = 42.0
        sensor._attr_available = True

        sensor._handle_availability_update(False)
        sensor._handle_measurement_update(description.odb_id, "unavailable")

        self.assertTrue(sensor._attr_available)
        self.assertEqual(sensor._attr_native_value, 42.0)
        self.assertEqual(writes, [])

    def test_recorded_attribute_changes_write_when_value_is_unchanged(self) -> None:
        sensor_module = _load_sensor_module()
        description = next(
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.key == "energy_consumption_total"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None

            def __init__(self) -> None:
                self.last_measurement_attributes = {
                    description.odb_id: {
                        "source_command": "set:ste.app.consumption:energyYears",
                        "chart": [20.0],
                        "cost_eur": 2.0,
                    }
                }

        client = _FakeClient()
        sensor = sensor_module.StiebelDHESensor(
            entry_id="test-entry",
            name="Test DHE",
            client=client,
            description=description,
        )
        writes: list[float | str | None] = []
        sensor.async_write_ha_state = lambda: writes.append(sensor._attr_native_value)
        sensor._attr_extra_state_attributes = {
            "source_command": "set:ste.app.consumption:energyYears",
            "period": "years",
            "chart": [20.0],
            "cost_eur": 1.0,
        }
        sensor._last_written_native_value = 20.0
        sensor._last_written_monotonic = time.monotonic()
        sensor._last_written_recorded_attributes = sensor._recorded_state_attributes()

        sensor._handle_measurement_update(description.odb_id, 20.0)

        self.assertEqual(
            writes,
            [20.0],
        )

    def test_unrecorded_attribute_changes_still_respect_value_filter(self) -> None:
        sensor_module = _load_sensor_module()
        description = next(
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.key == "energy_consumption_total"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None

            def __init__(self) -> None:
                self.last_measurement_attributes = {
                    description.odb_id: {
                        "source_command": "set:ste.app.consumption:energyYears",
                        "chart": [10.0, 10.01],
                        "cost_eur": 1.0,
                    }
                }

        client = _FakeClient()
        sensor = sensor_module.StiebelDHESensor(
            entry_id="test-entry",
            name="Test DHE",
            client=client,
            description=description,
        )
        writes: list[float | str | None] = []
        sensor.async_write_ha_state = lambda: writes.append(sensor._attr_native_value)
        sensor._attr_extra_state_attributes = {
            "source_command": "set:ste.app.consumption:energyYears",
            "period": "years",
            "chart": [10.0],
            "cost_eur": 1.0,
        }
        sensor._last_written_native_value = 20.0
        sensor._last_written_monotonic = time.monotonic()
        sensor._last_written_recorded_attributes = sensor._recorded_state_attributes()

        sensor._handle_measurement_update(description.odb_id, 20.01)

        self.assertEqual(writes, [])

    def test_unrecorded_saving_monitor_details_do_not_write_without_value_change(self) -> None:
        sensor_module = _load_sensor_module()
        description = next(
            item
            for item in sensor_module.SENSOR_DESCRIPTIONS
            if item.key == "saving_monitor_possible_energy"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None

            def __init__(self) -> None:
                self.last_measurement_attributes = {
                    description.odb_id: {
                        "source_command": "set:ste.app.savingMonitor:possible",
                        "saving_monitor_category": "possible",
                        "saving_monitor_field": "energy_kwh",
                        "possible": {
                            "water_l": 4.0,
                            "energy_kwh": 2.0,
                            "co2_kg": 0.5,
                        },
                    }
                }

        client = _FakeClient()
        sensor = sensor_module.StiebelDHESensor(
            entry_id="test-entry",
            name="Test DHE",
            client=client,
            description=description,
        )
        writes: list[float | str | None] = []
        sensor.async_write_ha_state = lambda: writes.append(sensor._attr_native_value)
        sensor._attr_extra_state_attributes = {
            "source_command": "set:ste.app.savingMonitor:possible",
            "saving_monitor_category": "possible",
            "saving_monitor_field": "energy_kwh",
            "possible": {
                "water_l": 3.0,
                "energy_kwh": 2.0,
                "co2_kg": 0.5,
            },
        }
        sensor._last_written_native_value = 2.0
        sensor._last_written_monotonic = time.monotonic()
        sensor._last_written_recorded_attributes = sensor._recorded_state_attributes()

        sensor._handle_measurement_update(description.odb_id, 2.0)

        self.assertEqual(writes, [])
        self.assertEqual(
            sensor._attr_extra_state_attributes["possible"]["water_l"],
            4.0,
        )

    def test_error_status_sensor_does_not_write_for_inlet_jitter(self) -> None:
        sensor_module = _load_sensor_module()

        sensor = sensor_module.StiebelDHEErrorStatusSensor(
            entry_id="test-entry",
            name="Test DHE",
            client=_fake_error_status_client(),
        )
        writes: list[str | None] = []
        sensor.async_write_ha_state = lambda: writes.append(sensor._attr_native_value)
        sensor._setpoint = 38.0
        sensor._inlet_temperature = 10.0
        sensor._update_status()
        sensor._write_status_state(force=True)
        writes.clear()

        sensor._handle_measurement_update(sensor_module.ID_INLET_TEMPERATURE, 10.1)
        sensor._handle_measurement_update(sensor_module.ID_INLET_TEMPERATURE, 10.3)

        self.assertEqual(writes, [])

        sensor._handle_measurement_update(sensor_module.ID_INLET_TEMPERATURE, 38.1)

        self.assertEqual(writes, ["target_below_inlet"])
        self.assertEqual(sensor._attr_native_value, "target_below_inlet")

        sensor._handle_measurement_update(sensor_module.ID_INLET_TEMPERATURE, 38.3)

        self.assertEqual(writes, ["target_below_inlet"])

    def test_error_status_sensor_refreshes_inlet_attributes_after_interval(self) -> None:
        sensor_module = _load_sensor_module()

        sensor = sensor_module.StiebelDHEErrorStatusSensor(
            entry_id="test-entry",
            name="Test DHE",
            client=_fake_error_status_client(),
        )
        writes: list[str | None] = []
        sensor.async_write_ha_state = lambda: writes.append(sensor._attr_native_value)
        sensor._setpoint = 38.0
        sensor._inlet_temperature = 10.0
        sensor._update_status()
        sensor._write_status_state(force=True)
        writes.clear()

        sensor._last_inlet_attribute_write_monotonic = -1_000_000_000.0
        sensor._handle_measurement_update(sensor_module.ID_INLET_TEMPERATURE, 10.2)

        self.assertEqual(writes, ["ok"])

    def test_error_status_sensor_writes_for_device_status_change(self) -> None:
        sensor_module = _load_sensor_module()

        sensor = sensor_module.StiebelDHEErrorStatusSensor(
            entry_id="test-entry",
            name="Test DHE",
            client=_fake_error_status_client(),
        )
        writes: list[str | None] = []
        sensor.async_write_ha_state = lambda: writes.append(sensor._attr_native_value)
        sensor._setpoint = 38.0
        sensor._inlet_temperature = 10.0
        sensor._update_status()
        sensor._write_status_state(force=True)
        writes.clear()

        sensor._handle_measurement_update(
            sensor_module.ID_DEVICE_STATUS,
            sensor_module.DEVICE_STATUS_SERVICE_REQUIRED,
        )

        self.assertEqual(writes, ["service_required"])
        self.assertEqual(sensor._attr_native_value, "service_required")


if __name__ == "__main__":
    unittest.main()
