"""Tests for climate recorder write filtering."""

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
    """Validate climate recorder filtering for high-churn telemetry."""

    def test_inlet_updates_do_not_write_climate_state_without_threshold_change(
        self,
    ) -> None:
        climate_module = _load_climate_module()
        entity = _build_entity(climate_module)
        entity._attr_target_temperature = 60.0

        calls: list[str] = []
        entity.async_write_ha_state = lambda: calls.append("write")

        entity._handle_measurement_update(climate_module.ID_INLET_TEMPERATURE, 10.0)
        entity._handle_measurement_update(climate_module.ID_INLET_TEMPERATURE, 10.2)
        entity._handle_measurement_update(climate_module.ID_INLET_TEMPERATURE, 10.7)

        self.assertEqual(calls, [])
        self.assertEqual(entity._inlet_temperature, 10.7)
        self.assertNotIn("inlet_temperature", entity._attr_extra_state_attributes)

    def test_outlet_updates_do_not_write_climate_state(self) -> None:
        climate_module = _load_climate_module()
        entity = _build_entity(climate_module)

        calls: list[str] = []
        entity.async_write_ha_state = lambda: calls.append("write")

        entity._handle_measurement_update(climate_module.ID_OUTLET_TEMPERATURE, 35.0)
        entity._handle_measurement_update(climate_module.ID_OUTLET_TEMPERATURE, 35.1)
        entity._handle_measurement_update(climate_module.ID_OUTLET_TEMPERATURE, 35.8)

        self.assertEqual(calls, [])
        self.assertEqual(entity._outlet_temperature, 35.8)
        self.assertNotIn("outlet_temperature", entity._attr_extra_state_attributes)

    def test_initial_temperature_sync_does_not_expose_high_churn_attributes(
        self,
    ) -> None:
        climate_module = _load_climate_module()
        client = _FakeClimateClient()
        client.last_measurements = {
            climate_module.ID_INLET_TEMPERATURE: 10.0,
            climate_module.ID_OUTLET_TEMPERATURE: 35.0,
        }
        entity = _build_entity(climate_module, client)

        entity._sync_temperatures_from_measurements()
        entity._update_extra_state_attributes()

        self.assertEqual(entity._inlet_temperature, 10.0)
        self.assertEqual(entity._outlet_temperature, 35.0)
        self.assertNotIn("inlet_temperature", entity._attr_extra_state_attributes)
        self.assertNotIn("outlet_temperature", entity._attr_extra_state_attributes)

    def test_target_below_inlet_entry_writes_despite_telemetry_suppression(
        self,
    ) -> None:
        climate_module = _load_climate_module()
        entity = _build_entity(climate_module)
        entity._attr_target_temperature = 38.0

        calls: list[str] = []
        entity.async_write_ha_state = lambda: calls.append("write")

        entity._handle_measurement_update(climate_module.ID_INLET_TEMPERATURE, 37.9)
        self.assertEqual(calls, [])

        entity._handle_measurement_update(climate_module.ID_INLET_TEMPERATURE, 38.1)
        self.assertEqual(calls, ["write"])
        self.assertTrue(
            entity._attr_extra_state_attributes["setpoint_below_inlet_temperature"]
        )

    def test_inlet_updates_write_while_target_remains_below_inlet(self) -> None:
        climate_module = _load_climate_module()
        entity = _build_entity(climate_module)
        entity._attr_target_temperature = 38.0

        calls: list[str] = []
        entity.async_write_ha_state = lambda: calls.append("write")

        entity._handle_measurement_update(climate_module.ID_INLET_TEMPERATURE, 38.1)
        entity._handle_measurement_update(climate_module.ID_INLET_TEMPERATURE, 38.4)

        self.assertEqual(calls, ["write", "write"])
        self.assertEqual(
            entity._attr_extra_state_attributes["inlet_minus_setpoint"],
            0.4,
        )

    def test_target_below_inlet_exit_writes_despite_telemetry_suppression(
        self,
    ) -> None:
        climate_module = _load_climate_module()
        entity = _build_entity(climate_module)
        entity._attr_target_temperature = 38.0

        calls: list[str] = []
        entity.async_write_ha_state = lambda: calls.append("write")

        entity._handle_measurement_update(climate_module.ID_INLET_TEMPERATURE, 38.1)
        self.assertEqual(calls, ["write"])

        entity._handle_measurement_update(climate_module.ID_INLET_TEMPERATURE, 37.9)
        self.assertEqual(calls, ["write", "write"])
        self.assertFalse(
            entity._attr_extra_state_attributes["setpoint_below_inlet_temperature"]
        )

    def test_repeated_heating_state_measurement_is_not_rewritten(self) -> None:
        climate_module = _load_climate_module()
        entity = _build_entity(climate_module)

        calls: list[str] = []
        entity.async_write_ha_state = lambda: calls.append("write")

        entity._handle_measurement_update(
            climate_module.ID_WATER_HEATING_ENABLED,
            True,
        )
        entity._handle_measurement_update(
            climate_module.ID_WATER_HEATING_ENABLED,
            True,
        )
        entity._handle_measurement_update(
            climate_module.ID_WATER_HEATING_ENABLED,
            False,
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(entity._attr_hvac_mode, climate_module.HVACMode.OFF)

    def test_repeated_setpoint_update_is_not_rewritten(self) -> None:
        climate_module = _load_climate_module()
        entity = _build_entity(climate_module)

        calls: list[str] = []
        entity.async_write_ha_state = lambda: calls.append("write")

        entity._handle_setpoint_update(38.0)
        entity._handle_setpoint_update(38.0)
        entity._handle_setpoint_update(39.0)

        self.assertEqual(len(calls), 2)
        self.assertEqual(entity._attr_target_temperature, 39.0)


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

    async def test_set_temperature_unavailable_raises_without_client_call(self) -> None:
        climate_module = _load_climate_module()
        from homeassistant.exceptions import HomeAssistantError

        client = _FakeClimateClient()
        client.available = False
        entity = _build_entity(climate_module, client)
        entity.async_write_ha_state = Mock()

        with self.assertRaisesRegex(
            HomeAssistantError,
            "DHE is unavailable",
        ):
            await entity.async_set_temperature(temperature=39.0)

        self.assertEqual(client.temperature_calls, [])
        self.assertEqual(client.heating_calls, [])


if __name__ == "__main__":
    unittest.main()
