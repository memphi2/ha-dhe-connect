"""Tests for weather entity state-write behavior."""

from __future__ import annotations

from datetime import UTC, datetime
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


def _ensure_additional_ha_stubs() -> None:
    from homeassistant import __dict__ as homeassistant_dict
    from homeassistant.components import __dict__ as components_dict

    if "weather" not in components_dict:
        weather_module = types.ModuleType("homeassistant.components.weather")

        class WeatherEntity:
            pass

        class WeatherEntityFeature(int):
            FORECAST_DAILY = 1

        weather_module.WeatherEntity = WeatherEntity
        weather_module.WeatherEntityFeature = WeatherEntityFeature
        sys.modules["homeassistant.components.weather"] = weather_module
        components_dict["weather"] = weather_module

    util_module = sys.modules.get("homeassistant.util")
    if util_module is None:
        util_module = types.ModuleType("homeassistant.util")
        sys.modules["homeassistant.util"] = util_module
        homeassistant_dict["util"] = util_module

    if "homeassistant.util.dt" not in sys.modules:
        dt_module = types.ModuleType("homeassistant.util.dt")
        dt_module.now = lambda: datetime(2026, 5, 16, 12, tzinfo=UTC)
        sys.modules["homeassistant.util.dt"] = dt_module
        util_module.dt = dt_module


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


def _load_weather_module():
    _load_component_module("client_mapping")
    _load_component_module("client")
    _load_component_module("entity_helpers")
    _load_component_module("entity_state_helpers")
    _load_component_module("runtime_helpers")
    _load_component_module("weather_mapping")
    return _load_component_module("weather")


def _weather_state() -> dict:
    location = {"Name": "Las Vegas", "Country": "USA", "LocationId": "ID=1"}
    return {
        "location": location,
        "favorites": [location],
        "simple_days": [
            {
                "date": "2026-05-16",
                "icon_id_day": 1,
                "tmax": 32.0,
                "tmin": 21.0,
            }
        ],
    }


class TestWeatherEntityWrites(unittest.TestCase):
    """Validate weather entity write throttling."""

    def test_weather_entity_skips_duplicate_state_writes(self) -> None:
        weather_module = _load_weather_module()
        state = _weather_state()

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            legacy_device_identifier = None
            available = True
            last_weather_state = state

        entity = weather_module.StiebelDHEWeather(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
        )
        writes: list[str | None] = []
        listener_updates: list[tuple[str, ...]] = []
        entity.async_write_ha_state = lambda: writes.append(entity._attr_condition)
        entity.async_update_listeners = lambda value: listener_updates.append(value)

        entity._handle_weather_update(_weather_state())
        entity._handle_weather_update(_weather_state())
        entity._handle_availability_update(True)
        entity._handle_availability_update(False)

        self.assertEqual(writes, ["sunny", "sunny"])
        self.assertEqual(listener_updates, [("daily",)])
        self.assertFalse(entity._attr_available)

    def test_weather_write_signature_ignores_unrecorded_list_payloads(self) -> None:
        weather_module = _load_weather_module()
        entity = weather_module.StiebelDHEWeather.__new__(
            weather_module.StiebelDHEWeather
        )
        entity._attr_available = True
        entity._attr_condition = "sunny"
        entity._attr_native_temperature = 32.0
        entity._attr_name = "Las Vegas, USA"
        entity._forecast = [{"datetime": "2026-05-16T00:00:00+00:00"}]
        entity._attr_extra_state_attributes = {
            "weather_path": "ste.app.weather",
            "favorite_count": 1,
            "favorite_locations": [{"name": "Las Vegas", "location_id": "ID=1"}],
            "forecast_results": [{"name": "Las Vegas", "location_id": "ID=1"}],
            "int_names": [{"Name": "Las Vegas", "Language": "en"}],
        }

        first_signature = entity._weather_write_signature()
        entity._attr_extra_state_attributes["favorite_locations"] = [
            {"name": "Las Vegas", "location_id": "ID=1", "search_type": 1}
        ]
        entity._attr_extra_state_attributes["forecast_results"] = [
            {"name": "Las Vegas", "location_id": "ID=1", "search_type": 1}
        ]
        entity._attr_extra_state_attributes["int_names"] = [
            {"Name": "Las Vegas", "Language": "de"}
        ]

        self.assertIn("favorite_locations", entity._unrecorded_attributes)
        self.assertIn("forecast_results", entity._unrecorded_attributes)
        self.assertIn("int_names", entity._unrecorded_attributes)
        self.assertEqual(first_signature, entity._weather_write_signature())


if __name__ == "__main__":
    unittest.main()
