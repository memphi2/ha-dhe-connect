"""Tests for temperature-memory number recreation paths."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock

try:
    from tests.test_aiohttp_stubs import _ensure_aiohttp_stub
except ModuleNotFoundError:
    from test_aiohttp_stubs import _ensure_aiohttp_stub

ROOT = Path(__file__).resolve().parents[1]
COMPONENT_DIR = ROOT / "custom_components" / "stiebel_dhe_connect"
PACKAGE_NAME = "custom_components.stiebel_dhe_connect"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_number_stubs() -> None:
    from homeassistant.components import __dict__ as components_dict

    if "number" in components_dict:
        return

    number_module = types.ModuleType("homeassistant.components.number")

    class NumberDeviceClass:
        TEMPERATURE = "temperature"
        VOLUME = "volume"
        VOLUME_FLOW_RATE = "volume_flow_rate"

    class NumberMode:
        BOX = "box"

    class RestoreNumber:
        async def async_get_last_number_data(self):
            return None

    @dataclass(frozen=True, kw_only=True)
    class NumberEntityDescription:
        key: str | None = None
        translation_key: str | None = None
        icon: str | None = None
        native_unit_of_measurement: str | None = None
        device_class: str | None = None
        native_min_value: float | int | None = None
        native_max_value: float | int | None = None
        native_step: float | int | None = None
        mode: str | None = None
        entity_registry_enabled_default: bool = True

    number_module.NumberDeviceClass = NumberDeviceClass
    number_module.NumberEntityDescription = NumberEntityDescription
    number_module.NumberMode = NumberMode
    number_module.RestoreNumber = RestoreNumber
    sys.modules["homeassistant.components.number"] = number_module
    components_dict["number"] = number_module


def _load_component_module(module_name: str):
    _ensure_aiohttp_stub()
    try:
        from tests.test_ha_stubs import ensure_homeassistant_stubs
    except ModuleNotFoundError:
        from test_ha_stubs import ensure_homeassistant_stubs

    ensure_homeassistant_stubs()
    _ensure_number_stubs()

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


def _load_number_module():
    _load_component_module("client_mapping")
    _load_component_module("flow_helpers")
    _load_component_module("pairing_helpers")
    _load_component_module("protocol")
    _load_component_module("client")
    _load_component_module("config_entry_helpers")
    _load_component_module("entity_helpers")
    _load_component_module("entity_state_helpers")
    _load_component_module("runtime_helpers")
    return _load_component_module("number")


def _memory_number(number_module, *, slot: int = 3, measurement_id: int = 700):
    entity = number_module.StiebelDHENumber.__new__(number_module.StiebelDHENumber)
    entity.entity_description = number_module._temperature_memory_number_description(
        slot,
        measurement_id,
    )
    entity._client = types.SimpleNamespace(
        available=True,
        set_temperature_memory=AsyncMock(return_value=39.5),
    )
    entity._attr_native_value = 38.0
    entity._base_extra_state_attributes = {"temperature_memory_slot": slot}
    entity._timer_duration_seconds = None
    entity._child_safety_temperature_limit_raw = None
    entity._internal_scald_protection = "60"
    entity.async_write_ha_state = Mock()
    return entity


class TestTemperatureMemoryNumbers(unittest.IsolatedAsyncioTestCase):
    """Validate deleted memory slots keep an in-HA creation path."""

    def test_memory_number_descriptions_cover_all_slots(self) -> None:
        number_module = _load_number_module()

        descriptions = [
            number_module._temperature_memory_number_description(slot, measurement_id)
            for measurement_id, slot in number_module.TEMPERATURE_MEMORY_MEASUREMENT_SLOT_ITEMS
        ]

        self.assertEqual(
            [description.temperature_memory_slot for description in descriptions],
            list(range(1, 13)),
        )
        self.assertTrue(descriptions[0].entity_registry_enabled_default)
        self.assertTrue(descriptions[1].entity_registry_enabled_default)
        self.assertFalse(descriptions[2].entity_registry_enabled_default)

    def test_deleted_memory_slot_stays_available_for_recreation(self) -> None:
        number_module = _load_number_module()
        entity = _memory_number(number_module)

        entity._handle_measurement_update(entity.entity_description.odb_id, None)

        self.assertIsNone(entity._attr_native_value)
        self.assertTrue(entity._attr_available)
        self.assertEqual(
            entity._attr_extra_state_attributes,
            {"temperature_memory_slot": 3},
        )
        entity.async_write_ha_state.assert_called_once()

    async def test_deleted_memory_slot_can_be_written_again(self) -> None:
        number_module = _load_number_module()
        entity = _memory_number(number_module)
        entity._attr_native_value = None

        await entity.async_set_native_value(39.5)

        entity._client.set_temperature_memory.assert_awaited_once_with(3, 39.5)
        self.assertEqual(entity._attr_native_value, 39.5)
        self.assertTrue(entity._attr_available)
        entity.async_write_ha_state.assert_called_once()

    def test_repeated_number_measurement_is_not_rewritten(self) -> None:
        number_module = _load_number_module()
        description = next(
            item
            for item in number_module.STATIC_NUMBER_DESCRIPTIONS
            if item.key == "eco_flow_limit"
        )

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            legacy_device_identifier = None
            available = True
            last_measurement_attributes = {}

        entity = number_module.StiebelDHENumber(
            entry=types.SimpleNamespace(data={}, options={}),
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
            description=description,
        )
        writes: list[float | None] = []
        entity.async_write_ha_state = lambda: writes.append(entity._attr_native_value)

        entity._handle_measurement_update(description.odb_id, 8.0)
        entity._handle_measurement_update(description.odb_id, 8.0)
        entity._handle_availability_update(True)
        entity._handle_measurement_update(description.odb_id, 8.5)

        self.assertEqual(writes, [8.0, 8.5])

    async def test_restored_static_number_value_stays_unavailable_offline(self) -> None:
        number_module = _load_number_module()
        description = next(
            item
            for item in number_module.STATIC_NUMBER_DESCRIPTIONS
            if item.key == "shower_timer_duration"
        )

        class _OfflineClient:
            host = "127.0.0.1"
            port = 8443
            legacy_device_identifier = None
            available = False
            last_measurements = {}
            last_measurement_attributes = {}

            def add_measurement_callback(self, _callback, *, replay=True):
                return lambda: None

            def add_availability_callback(self, _callback):
                return lambda: None

        entity = number_module.StiebelDHENumber(
            entry=types.SimpleNamespace(data={}, options={}),
            entry_id="test-entry",
            name="Test DHE",
            client=_OfflineClient(),
            description=description,
        )
        entity.async_on_remove = lambda _remove: None
        entity.async_get_last_number_data = AsyncMock(
            return_value=types.SimpleNamespace(native_value=300)
        )

        await entity.async_added_to_hass()

        self.assertEqual(entity._attr_native_value, 300)
        self.assertFalse(entity._attr_available)


if __name__ == "__main__":
    unittest.main()
