"""Real Home Assistant integration regression tests."""

from __future__ import annotations

import importlib
import types
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import loader
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    entity_registry as er,
)

from tests.ha_test_support import (
    DOMAIN,
    _async_test_home_assistant,
    _build_mock_entry,
    _clear_loaded_integration_modules,
    _FixtureDHEClient,
    _isolate_discovery_cache,  # noqa: F401 - registers the pytest fixture
)

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("temperature", ["nan", "inf", "-inf"])
async def test_climate_service_rejects_nonfinite_temperature(temperature: str) -> None:
    """HA's service schema must not turn invalid input into a heating command."""
    from homeassistant.components.climate import HVACMode
    from homeassistant.components.climate.services import (
        SET_TEMPERATURE_SCHEMA,
        _async_service_temperature_set,
    )
    from homeassistant.util.unit_system import METRIC_SYSTEM

    _clear_loaded_integration_modules()
    module = importlib.import_module(f"custom_components.{DOMAIN}.climate")
    client = types.SimpleNamespace(
        host="example.invalid", port=8443, available=True, last_device_info={},
        set_temperature=AsyncMock(), set_water_heating_enabled=AsyncMock(),
    )
    entity = module.StiebelDHEClimate(
        types.SimpleNamespace(data={}, options={}), "finite-test", "Test", client,
    )
    entity.hass = types.SimpleNamespace(config=types.SimpleNamespace(units=METRIC_SYSTEM))
    entity._attr_hvac_mode = HVACMode.OFF
    entity._water_heating_enabled = False
    data = SET_TEMPERATURE_SCHEMA({"entity_id": "climate.test", "temperature": temperature})
    with pytest.raises(HomeAssistantError):
        await _async_service_temperature_set(entity, types.SimpleNamespace(data=data))
    client.set_temperature.assert_not_called()
    client.set_water_heating_enabled.assert_not_called()



async def test_async_setup_registers_services_before_entry_load() -> None:
    """Register integration services at domain setup time."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with _async_test_home_assistant() as hass:
        assert await integration.async_setup(hass, {})
        assert hass.services.has_service(DOMAIN, "search_weather_location")

        with pytest.raises(HomeAssistantError, match="not loaded"):
            await hass.services.async_call(
                DOMAIN,
                "search_weather_location",
                {"name": "Berlin", "country_id": 49},
                blocking=True,
            )



async def test_multiple_entries_keep_services_and_unique_ids_separate() -> None:
    """Load two DHE entries and verify service lifetime plus entity IDs."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client_one = _FixtureDHEClient(host="127.0.0.1", port=8443)
        client_two = _FixtureDHEClient(host="127.0.0.2", port=8444)
        entry_one = _build_mock_entry(
            host=client_one.host,
            port=client_one.port,
            name="Fixture DHE One",
            unique_id="fixture-dhe-one",
        )
        entry_two = _build_mock_entry(
            host=client_two.host,
            port=client_two.port,
            name="Fixture DHE Two",
            unique_id="fixture-dhe-two",
        )
        entry_one.add_to_hass(hass)
        entry_two.add_to_hass(hass)

        with (
            patch.object(
                integration,
                "DHEClient",
                side_effect=lambda **kwargs: {
                    client_one.host: client_one, client_two.host: client_two,
                }[kwargs["host"]],
            ),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry_one.entry_id)
            if entry_two.state is ConfigEntryState.NOT_LOADED:
                assert await hass.config_entries.async_setup(entry_two.entry_id)
            await hass.async_block_till_done()

        registry = er.async_get(hass)
        climate_entries = [
            entity
            for entity in er.async_entries_for_config_entry(registry, entry_one.entry_id)
            + er.async_entries_for_config_entry(registry, entry_two.entry_id)
            if entity.domain == "climate"
        ]
        unique_ids = {entity.unique_id for entity in climate_entries}

        assert entry_one.state is ConfigEntryState.LOADED
        assert entry_two.state is ConfigEntryState.LOADED
        assert len(climate_entries) == 2
        assert len(unique_ids) == 2
        assert any(entry_one.entry_id in unique_id for unique_id in unique_ids)
        assert any(entry_two.entry_id in unique_id for unique_id in unique_ids)
        assert hass.services.has_service(DOMAIN, "search_weather_location")

        assert await hass.config_entries.async_unload(entry_one.entry_id)
        await hass.async_block_till_done()
        assert client_one.stop_called
        assert hass.services.has_service(DOMAIN, "search_weather_location")

        assert await hass.config_entries.async_unload(entry_two.entry_id)
        await hass.async_block_till_done()
        assert client_two.stop_called
        assert not hass.services.has_service(DOMAIN, "search_weather_location")



async def test_services_route_to_requested_entry_with_real_hass_fixture() -> None:
    """Call registered services through HA and verify entry_id routing."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client_one = _FixtureDHEClient(host="127.0.0.1", port=8443)
        client_two = _FixtureDHEClient(host="127.0.0.2", port=8444)
        client_one.weather_search_results = [
            {"LocationId": "one", "Name": "One", "Country": "Test"}
        ]
        client_two.weather_search_results = [
            {"LocationId": "two", "Name": "Two", "Country": "Test"}
        ]
        entry_one = _build_mock_entry(
            host=client_one.host,
            port=client_one.port,
            name="Fixture DHE One",
            unique_id="fixture-service-one",
        )
        entry_two = _build_mock_entry(
            host=client_two.host,
            port=client_two.port,
            name="Fixture DHE Two",
            unique_id="fixture-service-two",
        )
        entry_one.add_to_hass(hass)
        entry_two.add_to_hass(hass)

        with (
            patch.object(
                integration,
                "DHEClient",
                side_effect=lambda **kwargs: {
                    client_one.host: client_one, client_two.host: client_two,
                }[kwargs["host"]],
            ),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry_one.entry_id)
            if entry_two.state is ConfigEntryState.NOT_LOADED:
                assert await hass.config_entries.async_setup(entry_two.entry_id)
            await hass.async_block_till_done()

        await hass.services.async_call(
            DOMAIN,
            "search_weather_location",
            {
                "entry_id": entry_two.entry_id,
                "name": "Berlin",
                "country_id": 34,
            },
            blocking=True,
        )
        await hass.services.async_call(
            DOMAIN,
            "add_weather_favorite",
            {
                "entry_id": entry_two.entry_id,
                "location_id": "two",
            },
            blocking=True,
        )

        assert client_one.weather_search_calls == []
        assert client_one.weather_add_calls == []
        assert client_two.weather_search_calls == [("Berlin", 34)]
        assert client_two.weather_add_calls == [
            {"LocationId": "two", "Name": "Two", "Country": "Test"}
        ]

        with pytest.raises(HomeAssistantError, match="Multiple .* entry_id"):
            await hass.services.async_call(
                DOMAIN,
                "search_weather_location",
                {
                    "name": "Hamburg",
                    "country_id": 34,
                },
                blocking=True,
            )

        assert await hass.config_entries.async_unload(entry_one.entry_id)
        assert await hass.config_entries.async_unload(entry_two.entry_id)
        await hass.async_block_till_done()



async def test_weather_services_use_cached_candidates_with_real_hass_fixture() -> None:
    """Verify weather services resolve cached results, favorites and raw IDs."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        client.last_weather_state = {
            "forecast_results": [
                {"LocationId": "result-one", "Name": "Result One"},
                {"LocationId": "result-two", "Name": "Result Two"},
            ],
            "favorites": [
                {"LocationId": "favorite-one", "Name": "Favorite One"},
            ],
            "location": {"LocationId": "current-one", "Name": "Current One"},
        }
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Weather Service Fixture DHE",
            unique_id="weather-service-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        await hass.services.async_call(
            DOMAIN,
            "add_weather_favorite",
            {"result_number": 2},
            blocking=True,
        )
        await hass.services.async_call(
            DOMAIN,
            "toggle_weather_favorite",
            {"location_id": "favorite-one"},
            blocking=True,
        )
        await hass.services.async_call(
            DOMAIN,
            "select_weather_location",
            {"location_id": "current-one"},
            blocking=True,
        )
        await hass.services.async_call(
            DOMAIN,
            "remove_weather_favorite",
            {"location_id": "raw-location-id"},
            blocking=True,
        )

        assert client.weather_search_calls == []
        assert client.weather_add_calls == [
            {"LocationId": "result-two", "Name": "Result Two"}
        ]
        assert client.weather_toggle_calls == [
            {"LocationId": "favorite-one", "Name": "Favorite One"}
        ]
        assert client.weather_select_calls == [
            {"LocationId": "current-one", "Name": "Current One"}
        ]
        assert client.weather_remove_calls == [{"LocationId": "raw-location-id"}]

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()



async def test_weather_service_dhe_errors_raise_homeassistant_error() -> None:
    """Convert DHE client failures into HA service errors without hiding them."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    client_types = importlib.import_module(
        f"custom_components.{DOMAIN}.client_types"
    )
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        client.last_weather_state = {
            "forecast_results": [
                {"LocationId": "result-one", "Name": "Result One"},
            ],
        }
        failure = client_types.DHEError("write failed")
        client.add_weather_favorite = AsyncMock(side_effect=failure)
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Weather Error Fixture DHE",
            unique_id="weather-error-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        with pytest.raises(
            HomeAssistantError,
            match="Could not add DHE weather favorite: write failed",
        ) as err_info:
            await hass.services.async_call(
                DOMAIN,
                "add_weather_favorite",
                {"result_number": 1},
                blocking=True,
            )

        assert err_info.value.__cause__ is failure
        client.add_weather_favorite.assert_awaited_once_with(
            {"LocationId": "result-one", "Name": "Result One"}
        )

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()



async def test_weather_service_unavailable_runtime_raises_homeassistant_error() -> None:
    """Block DHE service calls while the runtime is unavailable."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        client.available = False
        client.last_weather_state = {
            "forecast_results": [
                {"LocationId": "result-one", "Name": "Result One"},
            ],
        }
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Weather Unavailable Fixture DHE",
            unique_id="weather-unavailable-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        with pytest.raises(
            HomeAssistantError,
            match="DHE is unavailable; cannot add weather favorite",
        ):
            await hass.services.async_call(
                DOMAIN,
                "add_weather_favorite",
                {"result_number": 1},
                blocking=True,
            )

        assert client.weather_add_calls == []

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
