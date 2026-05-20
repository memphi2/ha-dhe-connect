"""Tests for select helper behavior."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import types
import sys
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


def _ensure_additional_ha_stubs() -> None:
    from homeassistant.components import __dict__ as components_dict

    if "select" not in components_dict:
        select_module = types.ModuleType("homeassistant.components.select")

        class SelectEntity:
            pass

        select_module.SelectEntity = SelectEntity
        sys.modules["homeassistant.components.select"] = select_module
        components_dict["select"] = select_module

    if "homeassistant.exceptions" not in sys.modules:
        exceptions_module = types.ModuleType("homeassistant.exceptions")

        class HomeAssistantError(Exception):
            pass

        exceptions_module.HomeAssistantError = HomeAssistantError
        sys.modules["homeassistant.exceptions"] = exceptions_module


def _load_component_module(module_name: str):
    _ensure_aiohttp_stub()
    try:
        from tests.test_ha_stubs import ensure_homeassistant_stubs
    except ModuleNotFoundError:
        from test_ha_stubs import ensure_homeassistant_stubs

    ensure_homeassistant_stubs()
    _ensure_additional_ha_stubs()
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


def _load_select_module():
    _load_component_module("client_mapping")
    _load_component_module("client")
    _load_component_module("entity_helpers")
    _load_component_module("entity_state_helpers")
    _load_component_module("runtime_helpers")
    _load_component_module("weather_mapping")
    return _load_component_module("select")


class TestSelectHelpers(unittest.IsolatedAsyncioTestCase):
    """Validate option and label helpers used by weather location select."""

    def test_weather_location_labels_use_location_id_for_exact_duplicates(self) -> None:
        select_module = _load_select_module()
        locations = [
            {"Name": "Berlin", "Country": "Germany", "LocationId": "ID=1"},
            {"Name": "Berlin", "Country": "Germany", "LocationId": "ID=2"},
        ]

        labels = select_module._weather_location_labels(locations)

        self.assertEqual(
            labels,
            [
                "Berlin, Germany (ID=1)",
                "Berlin, Germany (ID=2)",
            ],
        )

    def test_weather_location_labels_fall_back_to_numeric_suffixes(self) -> None:
        select_module = _load_select_module()
        locations = [{}, {}]

        labels = select_module._weather_location_labels(locations)

        self.assertEqual(labels, ["Unknown location", "Unknown location #2"])

    def test_weather_location_option_map_keeps_current_location(self) -> None:
        select_module = _load_select_module()
        favorites = [{"Name": "Hamburg", "Country": "Germany", "LocationId": "ID=2"}]
        current = {"Name": "Berlin", "Country": "Germany", "LocationId": "ID=1"}

        mapping = select_module._weather_location_option_map(
            favorites,
            current_location=current,
        )

        self.assertEqual(list(mapping.values())[0], current)
        self.assertEqual(len(mapping), 2)

    def test_weather_select_skips_duplicate_state_writes(self) -> None:
        select_module = _load_select_module()
        location = {"Name": "Berlin", "Country": "Germany", "LocationId": "ID=1"}
        state = {"location": location, "favorites": [location]}

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            legacy_device_identifier = None
            available = True
            last_weather_state = state

        entity = select_module.StiebelDHEWeatherLocationSelect(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
        )
        writes: list[str | None] = []
        entity.async_write_ha_state = lambda: writes.append(entity._attr_current_option)

        entity._handle_weather_update(dict(state))
        entity._handle_weather_update(dict(state))
        entity._handle_availability_update(True)
        entity._handle_availability_update(False)

        self.assertEqual(writes, ["Berlin, Germany", "Berlin, Germany"])
        self.assertFalse(entity._attr_available)

    async def test_unavailable_select_action_raises_without_client_call(self) -> None:
        select_module = _load_select_module()
        location = {"Name": "Berlin", "Country": "Germany", "LocationId": "ID=1"}
        select_weather_location = AsyncMock(return_value=True)
        client = types.SimpleNamespace(
            host="127.0.0.1",
            port=8443,
            legacy_device_identifier=None,
            available=False,
            select_weather_location=select_weather_location,
        )
        entity = select_module.StiebelDHEWeatherLocationSelect(
            entry_id="test-entry",
            name="Test DHE",
            client=client,
        )
        entity._locations_by_option = {"Berlin, Germany": location}

        with self.assertRaisesRegex(
            select_module.HomeAssistantError,
            "DHE is unavailable",
        ):
            await entity.async_select_option("Berlin, Germany")

        select_weather_location.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
