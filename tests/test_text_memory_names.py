"""Tests for temperature-memory text entity behavior."""

from __future__ import annotations

from dataclasses import dataclass
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


def _ensure_text_stubs() -> None:
    from homeassistant.components import __dict__ as components_dict
    from homeassistant.helpers import __dict__ as helpers_dict

    if "text" not in components_dict:
        text_module = types.ModuleType("homeassistant.components.text")

        class TextEntity:
            pass

        @dataclass(frozen=True, kw_only=True)
        class TextEntityDescription:
            key: str | None = None
            translation_key: str | None = None
            icon: str | None = None
            entity_registry_enabled_default: bool = True

        text_module.TextEntity = TextEntity
        text_module.TextEntityDescription = TextEntityDescription
        sys.modules["homeassistant.components.text"] = text_module
        components_dict["text"] = text_module

    if "restore_state" not in helpers_dict:
        restore_module = types.ModuleType("homeassistant.helpers.restore_state")

        class RestoreEntity:
            async def async_get_last_state(self):
                return None

        restore_module.RestoreEntity = RestoreEntity
        sys.modules["homeassistant.helpers.restore_state"] = restore_module
        helpers_dict["restore_state"] = restore_module


def _load_component_module(module_name: str):
    _ensure_aiohttp_stub()
    try:
        from tests.test_ha_stubs import ensure_homeassistant_stubs
    except ModuleNotFoundError:
        from test_ha_stubs import ensure_homeassistant_stubs

    ensure_homeassistant_stubs()
    _ensure_text_stubs()

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


def _load_text_module():
    _load_component_module("client_mapping")
    _load_component_module("client")
    _load_component_module("entity_helpers")
    _load_component_module("entity_state_helpers")
    _load_component_module("runtime_helpers")
    return _load_component_module("text")


class TestTemperatureMemoryText(unittest.TestCase):
    """Validate temperature-memory text write filtering."""

    def test_repeated_text_measurement_is_not_rewritten(self) -> None:
        text_module = _load_text_module()
        description = text_module._temperature_memory_text_description(1, 700)

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            legacy_device_identifier = None
            available = True
            last_measurement_attributes = {700: {"name": "Memory 1"}}

        entity = text_module.StiebelDHEText(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
            description=description,
        )
        writes: list[str | None] = []
        entity.async_write_ha_state = lambda: writes.append(entity._attr_native_value)

        entity._handle_measurement_update(description.measurement_id, 38.0)
        entity._handle_measurement_update(description.measurement_id, 38.0)
        entity._handle_availability_update(True)
        entity._client.last_measurement_attributes[700] = {"name": "Eco"}
        entity._handle_measurement_update(description.measurement_id, 39.0)

        self.assertEqual(writes, ["Memory 1", "Eco"])

    def test_restored_text_attributes_match_later_dhe_metadata(self) -> None:
        text_module = _load_text_module()
        description = text_module._temperature_memory_text_description(1, 700)

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            legacy_device_identifier = None
            available = True
            last_measurement_attributes = {}

        entity = text_module.StiebelDHEText(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
            description=description,
        )
        entity._attr_native_value = "Memory 1"
        entity._update_extra_state_attributes()
        restored_attributes = dict(entity._attr_extra_state_attributes)

        entity._client.last_measurement_attributes[700] = {
            "memory_id": 0,
            "name": "Memory 1",
            "source_command": "set:ste.common.temperature:memory",
        }
        entity._update_extra_state_attributes()

        self.assertEqual(entity._attr_extra_state_attributes, restored_attributes)


if __name__ == "__main__":
    unittest.main()
