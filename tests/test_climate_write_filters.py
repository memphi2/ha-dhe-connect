"""Tests for climate telemetry write filtering."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock

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


class _FakeClimateClient:
    host = "127.0.0.1"
    port = 8443
    legacy_device_identifier = None
    available = True

    def __init__(self) -> None:
        self.last_measurements = {}
        self.last_setpoint = None
        self.heating_calls: list[bool] = []
        self.temperature_calls: list[float] = []

    async def set_water_heating_enabled(self, enabled: bool) -> bool:
        self.heating_calls.append(enabled)
        self.last_measurements[33] = enabled
        return enabled

    async def set_temperature(self, temperature: float) -> float:
        self.temperature_calls.append(temperature)
        self.last_setpoint = temperature
        return temperature


def _build_entity(climate_module, client: _FakeClimateClient | None = None):
    entry = types.SimpleNamespace(data={}, options={})
    return climate_module.StiebelDHEClimate(
        entry=entry,
        entry_id="test-entry",
        name="Test DHE",
        client=client or _FakeClimateClient(),
    )


class TestClimateWriteFilters(unittest.TestCase):
    """Validate climate write throttling for high-churn telemetry."""

    def test_inlet_jitter_is_throttled_but_periodic_write_kept(self) -> None:
        climate_module = _load_climate_module()
        entity = _build_entity(climate_module)

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
        entity = _build_entity(climate_module)

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


class TestClimateHvacControls(unittest.IsolatedAsyncioTestCase):
    """Validate Home Assistant climate on/off service behavior."""

    async def test_turn_off_then_turn_on_restores_previous_target(self) -> None:
        climate_module = _load_climate_module()
        client = _FakeClimateClient()
        entity = _build_entity(climate_module, client)
        entity.async_write_ha_state = Mock()
        entity._attr_target_temperature = 42.0
        entity._water_heating_enabled = True

        await entity.async_turn_off()
        await entity.async_turn_on()

        self.assertEqual(client.heating_calls, [False, True])
        self.assertEqual(client.temperature_calls, [42.0])
        self.assertEqual(entity._attr_hvac_mode, climate_module.HVACMode.HEAT)
        self.assertEqual(entity._attr_target_temperature, 42.0)
        self.assertEqual(entity.async_write_ha_state.call_count, 2)

    async def test_set_temperature_enables_heating_when_hvac_is_off(self) -> None:
        climate_module = _load_climate_module()
        client = _FakeClimateClient()
        entity = _build_entity(climate_module, client)
        entity.async_write_ha_state = Mock()
        entity._attr_hvac_mode = climate_module.HVACMode.OFF
        entity._water_heating_enabled = False

        await entity.async_set_temperature(temperature=39.0)

        self.assertEqual(client.heating_calls, [True])
        self.assertEqual(client.temperature_calls, [39.0])
        self.assertEqual(entity._attr_hvac_mode, climate_module.HVACMode.HEAT)
        self.assertEqual(entity._attr_target_temperature, 39.0)
        entity.async_write_ha_state.assert_called_once()


if __name__ == "__main__":
    unittest.main()
