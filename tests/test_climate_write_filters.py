"""Tests for climate telemetry write filtering."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
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


def _load_climate_module():
    _load_component_module("client_mapping")
    _load_component_module("flow_helpers")
    _load_component_module("pairing_helpers")
    _load_component_module("protocol")
    _load_component_module("client")
    _load_component_module("config_entry_helpers")
    _load_component_module("entity_helpers")
    _load_component_module("entity_state_helpers")
    _load_component_module("runtime_helpers")
    return _load_component_module("climate")


class TestClimateWriteFilters(unittest.TestCase):
    """Validate climate write throttling for high-churn telemetry."""

    def _build_entity(self, climate_module):
        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            legacy_device_identifier = None
            last_measurements = {}
            last_setpoint = None
            available = True

        entry = types.SimpleNamespace(data={}, options={})
        entity = climate_module.StiebelDHEClimate(
            entry=entry,
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
        )
        return entity

    def test_inlet_jitter_is_throttled_but_periodic_write_kept(self) -> None:
        climate_module = _load_climate_module()
        entity = self._build_entity(climate_module)

        calls: list[str] = []
        entity.async_write_ha_state = lambda: calls.append("write")

        monotonic_value = 0.0
        original_monotonic = climate_module.time.monotonic
        climate_module.time.monotonic = lambda: monotonic_value
        try:
            entity._handle_measurement_update(climate_module.ID_INLET_TEMPERATURE, 10.0)
            self.assertEqual(len(calls), 1)

            monotonic_value = 10.0
            entity._handle_measurement_update(climate_module.ID_INLET_TEMPERATURE, 10.2)
            self.assertEqual(len(calls), 1)

            monotonic_value = 140.0
            entity._handle_measurement_update(climate_module.ID_INLET_TEMPERATURE, 10.3)
            self.assertEqual(len(calls), 2)
        finally:
            climate_module.time.monotonic = original_monotonic

    def test_outlet_large_delta_writes_immediately(self) -> None:
        climate_module = _load_climate_module()
        entity = self._build_entity(climate_module)

        calls: list[str] = []
        entity.async_write_ha_state = lambda: calls.append("write")

        monotonic_value = 0.0
        original_monotonic = climate_module.time.monotonic
        climate_module.time.monotonic = lambda: monotonic_value
        try:
            entity._handle_measurement_update(climate_module.ID_OUTLET_TEMPERATURE, 35.0)
            self.assertEqual(len(calls), 1)

            monotonic_value = 5.0
            entity._handle_measurement_update(climate_module.ID_OUTLET_TEMPERATURE, 35.1)
            self.assertEqual(len(calls), 1)

            monotonic_value = 7.0
            entity._handle_measurement_update(climate_module.ID_OUTLET_TEMPERATURE, 35.8)
            self.assertEqual(len(calls), 2)
        finally:
            climate_module.time.monotonic = original_monotonic


if __name__ == "__main__":
    unittest.main()
