"""Tests for recorder attribute exclusions on sensor entities."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import types
import sys
import time
import unittest
from unittest.mock import AsyncMock

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
        legacy_device_identifier=None,
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
            legacy_device_identifier = None

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
                "message_count": 1,
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
                "message_count": 2,
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

    def test_flow_and_power_write_filters_use_stricter_thresholds(self) -> None:
        sensor_module = _load_sensor_module()
        self.assertIn("water_flow", sensor_module.DEFAULT_ENABLED_SENSOR_KEYS)
        self.assertIn("power", sensor_module.DEFAULT_ENABLED_SENSOR_KEYS)
        self.assertEqual(sensor_module.SENSOR_WRITE_FILTERS["water_flow"], (1.0, 45.0))
        self.assertEqual(sensor_module.SENSOR_WRITE_FILTERS["power"], (1.5, 45.0))
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

    def test_flow_filter_blocks_small_jitter_but_allows_large_delta_or_interval(self) -> None:
        sensor_module = _load_sensor_module()
        description = next(
            item for item in sensor_module.SENSOR_DESCRIPTIONS if item.key == "water_flow"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            legacy_device_identifier = None

        sensor = sensor_module.StiebelDHESensor(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
            description=description,
        )
        sensor._last_written_native_value = 5.0
        sensor._last_written_monotonic = time.monotonic()

        self.assertFalse(sensor._should_write_measurement_state(5.4))
        self.assertTrue(sensor._should_write_measurement_state(6.1))

        sensor._last_written_native_value = 5.0
        sensor._last_written_monotonic = -1_000_000_000.0
        self.assertTrue(sensor._should_write_measurement_state(5.4))

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
            legacy_device_identifier = None

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
            legacy_device_identifier = None

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

    def test_availability_update_writes_only_on_effective_sensor_change(self) -> None:
        sensor_module = _load_sensor_module()
        description = next(
            item for item in sensor_module.SENSOR_DESCRIPTIONS if item.key == "water_flow"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            legacy_device_identifier = None

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
            legacy_device_identifier = None

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
            legacy_device_identifier = None

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
            legacy_device_identifier = None

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
            legacy_device_identifier = None

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
