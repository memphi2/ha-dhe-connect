"""Tests for recorder attribute exclusions on sensor entities."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import types
import sys
import time
import unittest

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

    def test_flow_and_power_write_filters_use_stricter_thresholds(self) -> None:
        sensor_module = _load_sensor_module()
        self.assertEqual(sensor_module.SENSOR_WRITE_FILTERS["water_flow"], (1.0, 45.0))
        self.assertEqual(sensor_module.SENSOR_WRITE_FILTERS["power"], (1.5, 45.0))
        self.assertEqual(
            sensor_module.SENSOR_WRITE_FILTERS["saving_monitor_consumption_water"],
            (0.25, 60.0),
        )
        self.assertEqual(
            sensor_module.SENSOR_WRITE_FILTERS["saving_monitor_activation_rate"],
            (1.0, 120.0),
        )

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


if __name__ == "__main__":
    unittest.main()
