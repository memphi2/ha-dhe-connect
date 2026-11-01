"""Tests for weather entity state-write behavior."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from datetime import UTC, datetime
from pathlib import Path
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
        weather_const = types.ModuleType("homeassistant.components.weather.const")
        weather_const.WeatherEntityFeature = WeatherEntityFeature
        sys.modules["homeassistant.components.weather.const"] = weather_const

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


def _weather_state(*, tmax: float = 32.0) -> dict:
    location = {"Name": "Las Vegas", "Country": "USA", "LocationId": "ID=1"}
    return {
        "location": location,
        "favorites": [location],
        "simple_days": [
            {
                "date": "2026-05-16",
                "icon_id_day": 1,
                "tmax": tmax,
                "tmin": 21.0,
            }
        ],
    }


class TestWeatherEntityWrites(unittest.IsolatedAsyncioTestCase):
    """Validate weather entity write throttling."""

    def test_malformed_weather_field_does_not_drop_valid_update(self) -> None:
        module = _load_weather_module()
        client = types.SimpleNamespace(host="127.0.0.1", port=8443,
                                       device_identifier=None, available=True)
        entity = module.StiebelDHEWeather("test-entry", "Test DHE", client)
        writes = []
        entity.async_write_ha_state = lambda: writes.append(entity._attr_native_temperature)
        state = _weather_state(tmax="NaN")
        state["simple_days"][0].update(icon_id_day="1e309", preci_morning="NaN")
        entity._handle_weather_update(state)
        self.assertEqual(writes, [21.0])
        self.assertTrue(entity._attr_available)
        self.assertNotIn("native_temperature", entity._forecast[0])
        entity._handle_weather_update(_weather_state())
        self.assertEqual(writes, [21.0, 26.5])


    async def test_weather_entity_skips_duplicate_state_writes(self) -> None:
        weather_module = _load_weather_module()
        state = _weather_state()

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None
            available = True
            last_weather_state = state

        entity = weather_module.StiebelDHEWeather(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
        )
        writes: list[str | None] = []
        entity.hass = types.SimpleNamespace(
            async_create_background_task=lambda coro, name: asyncio.create_task(coro, name=name)
        )
        entity.async_write_ha_state = lambda: writes.append(entity._attr_condition)
        entity.async_update_listeners = AsyncMock()
        entity._async_subscription_started("daily")

        entity._handle_weather_update(_weather_state())
        entity._handle_weather_update(_weather_state())
        entity._handle_availability_update(True)
        entity._handle_availability_update(False)
        await entity._forecast_listener_update_task

        self.assertEqual(writes, ["sunny", "sunny"])
        entity.async_update_listeners.assert_awaited_once_with(("daily",))
        self.assertFalse(entity._attr_available)

    def test_weather_entity_skips_listener_task_without_forecast_listeners(self) -> None:
        weather_module = _load_weather_module()
        state = _weather_state()

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None
            available = True
            last_weather_state = state

        class _FakeHass:
            def __init__(self) -> None:
                self.tasks: list[asyncio.Task[object]] = []

            def async_create_background_task(
                self,
                coro: object,
                name: str,
            ) -> asyncio.Task[object]:
                task = asyncio.create_task(coro, name=name)
                self.tasks.append(task)
                return task

        async def _run() -> None:
            hass = _FakeHass()
            entity = weather_module.StiebelDHEWeather(
                entry_id="test-entry",
                name="Test DHE",
                client=_FakeClient(),
            )
            entity.hass = hass
            entity.async_write_ha_state = lambda: None
            listener_updates: list[tuple[str, ...]] = []

            async def _async_update_listeners(value: tuple[str, ...]) -> None:
                listener_updates.append(value)

            entity.async_update_listeners = _async_update_listeners

            entity._handle_weather_update(_weather_state())

            self.assertEqual(hass.tasks, [])
            self.assertEqual(listener_updates, [])

        asyncio.run(_run())

    def test_weather_entity_coalesces_concurrent_listener_tasks(self) -> None:
        weather_module = _load_weather_module()
        state = _weather_state()

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None
            available = True
            last_weather_state = state

        class _FakeHass:
            def __init__(self) -> None:
                self.tasks: list[asyncio.Task[object]] = []

            def async_create_background_task(
                self,
                coro: object,
                name: str,
            ) -> asyncio.Task[object]:
                task = asyncio.create_task(coro, name=name)
                self.tasks.append(task)
                return task

        async def _run() -> None:
            hass = _FakeHass()
            release = asyncio.Event()
            listener_updates: list[tuple[str, ...]] = []
            entity = weather_module.StiebelDHEWeather(
                entry_id="test-entry",
                name="Test DHE",
                client=_FakeClient(),
            )
            entity.hass = hass
            entity.async_write_ha_state = lambda: None
            entity._async_subscription_started("daily")

            async def _async_update_listeners(value: tuple[str, ...]) -> None:
                listener_updates.append(value)
                await release.wait()

            entity.async_update_listeners = _async_update_listeners

            entity._handle_weather_update(_weather_state())
            await asyncio.sleep(0)
            entity._handle_weather_update(_weather_state(tmax=33.0))
            entity._handle_weather_update(_weather_state(tmax=34.0))

            self.assertEqual(len(hass.tasks), 1)
            self.assertTrue(entity._forecast_listener_update_pending)

            release.set()
            await asyncio.gather(*hass.tasks)
            await asyncio.sleep(0)
            await asyncio.gather(*hass.tasks)

            self.assertEqual(len(hass.tasks), 2)
            self.assertEqual(listener_updates, [("daily",), ("daily",)])
            self.assertIsNone(entity._forecast_listener_update_task)
            self.assertFalse(entity._forecast_listener_update_pending)

        asyncio.run(_run())

    def test_weather_entity_tracks_forecast_subscription_lifecycle(self) -> None:
        weather_module = _load_weather_module()
        state = _weather_state()

        class _FakeClient:
            host = "127.0.0.1"
            port = 8443
            device_identifier = None
            available = True
            last_weather_state = state

        entity = weather_module.StiebelDHEWeather(
            entry_id="test-entry",
            name="Test DHE",
            client=_FakeClient(),
        )

        self.assertFalse(entity._has_forecast_listeners())
        entity._async_subscription_started("daily")
        entity._async_subscription_started("daily")
        self.assertTrue(entity._has_forecast_listeners())
        entity._forecast_listener_update_pending = True
        entity._async_subscription_ended("daily")
        self.assertTrue(entity._has_forecast_listeners())
        self.assertTrue(entity._forecast_listener_update_pending)
        entity._async_subscription_ended("daily")
        self.assertFalse(entity._has_forecast_listeners())
        self.assertFalse(entity._forecast_listener_update_pending)

    def test_weather_write_signature_includes_unrecorded_list_payloads(self) -> None:
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
        self.assertNotEqual(first_signature, entity._weather_write_signature())

    def test_replaced_search_results_publish_without_forecast_notification(self) -> None:
        from copy import deepcopy
        from unittest.mock import Mock

        weather_module = _load_weather_module()
        client = types.SimpleNamespace(
            host="127.0.0.1", port=8443, device_identifier=None, available=True,
        )
        entity = weather_module.StiebelDHEWeather("test-entry", "Test DHE", client)
        snapshots = []
        entity.async_write_ha_state = lambda: snapshots.append(
            deepcopy(entity._attr_extra_state_attributes)
        )
        entity._schedule_forecast_listener_update = Mock()
        state = _weather_state()
        state["forecast_results"] = [{"Name": "First", "LocationId": "ID=1"}]
        entity._handle_weather_update(state)
        entity._schedule_forecast_listener_update.reset_mock()
        state["forecast_results"] = [{"Name": "Second", "LocationId": "ID=2"}]
        entity._handle_weather_update(state)
        entity._handle_weather_update(state)

        self.assertEqual(len(snapshots), 2)
        self.assertEqual(snapshots[-1]["forecast_results"][0]["name"], "Second")
        entity._schedule_forecast_listener_update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
