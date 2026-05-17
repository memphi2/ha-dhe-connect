"""Runtime tests using Home Assistant's real pytest fixtures."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import importlib
from pathlib import Path
import sys
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_test_home_assistant,
)

from homeassistant import config_entries, loader
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er


pytestmark = pytest.mark.asyncio
DOMAIN = "stiebel_dhe_connect"
DEFAULT_PORT = 8443
ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _FixtureDHEClient:
    """Minimal DHE client test double for real Home Assistant runtime setup."""

    host = "127.0.0.1"
    port = DEFAULT_PORT
    legacy_device_identifier = None
    available = True
    online = True
    reconnect_count = 0
    last_setpoint = 39.5

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = DEFAULT_PORT,
        last_setpoint: float = 39.5,
    ) -> None:
        self.host = host
        self.port = port
        self.last_setpoint = last_setpoint
        self.last_measurements: dict[int, Any] = {}
        self.last_measurement_attributes: dict[int, dict[str, Any]] = {}
        self.last_radio_state: dict[str, Any] = {}
        self.last_weather_state: dict[str, Any] = {}
        self.weather_search_results: list[dict[str, Any]] = []
        self.diagnostic_state: dict[str, Any] = {}
        self.start_called = False
        self.stop_called = False
        self.weather_search_calls: list[tuple[str, int]] = []
        self.weather_add_calls: list[dict[str, Any]] = []
        self.weather_toggle_calls: list[dict[str, Any]] = []
        self.weather_remove_calls: list[dict[str, Any]] = []
        self.weather_select_calls: list[dict[str, Any] | str] = []
        self.repair_pairing_calls = 0
        self._stopped = asyncio.Event()
        self.callbacks: dict[str, list[Callable[..., None]]] = {
            "availability": [],
            "diagnostic": [],
            "measurement": [],
            "radio": [],
            "reconnect": [],
            "setpoint": [],
            "weather": [],
        }

    async def start(self) -> None:
        """Mimic the long-running DHE background session."""
        self.start_called = True
        try:
            await self._stopped.wait()
        except asyncio.CancelledError:
            raise

    async def stop(self) -> None:
        """Stop the fake background session."""
        self.stop_called = True
        self._stopped.set()

    async def search_weather_locations(
        self,
        name: str,
        country_id: int,
    ) -> list[dict[str, Any]]:
        """Record a weather search and return configured fake results."""
        self.weather_search_calls.append((name, int(country_id)))
        self.last_weather_state["forecast_results"] = list(self.weather_search_results)
        self.emit_weather(self.last_weather_state)
        return list(self.weather_search_results)

    async def add_weather_favorite(self, location: dict[str, Any]) -> bool:
        """Record a weather favorite add call."""
        self.weather_add_calls.append(dict(location))
        return True

    async def toggle_weather_favorite(self, location: dict[str, Any]) -> bool:
        """Record a weather favorite toggle call."""
        self.weather_toggle_calls.append(dict(location))
        return True

    async def remove_weather_favorite(self, location: dict[str, Any]) -> bool:
        """Record a weather favorite remove call."""
        self.weather_remove_calls.append(dict(location))
        return True

    async def select_weather_location(self, location: dict[str, Any] | str) -> bool:
        """Record a weather location selection call."""
        if isinstance(location, dict):
            self.weather_select_calls.append(dict(location))
        else:
            self.weather_select_calls.append(str(location))
        return True

    async def repair_pairing(self) -> bool:
        """Record a repair pairing button call."""
        self.repair_pairing_calls += 1
        return True

    def emit_availability(self, available: bool) -> None:
        """Emit availability to registered entities."""
        self.available = available
        for callback_fn in list(self.callbacks["availability"]):
            callback_fn(available)

    def emit_weather(self, state: dict[str, Any]) -> None:
        """Emit weather state to registered entities."""
        self.last_weather_state = dict(state)
        for callback_fn in list(self.callbacks["weather"]):
            callback_fn(self.last_weather_state)

    def emit_measurement(
        self,
        odb_id: int,
        value: Any,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """Emit one measurement to registered entities."""
        self.last_measurements[odb_id] = value
        if attributes is not None:
            self.last_measurement_attributes[odb_id] = dict(attributes)
        for callback_fn in list(self.callbacks["measurement"]):
            callback_fn(odb_id, value)

    def emit_reconnect(self, reconnect_count: int) -> None:
        """Emit a reconnect-count update to registered entities."""
        self.reconnect_count = reconnect_count
        for callback_fn in list(self.callbacks["reconnect"]):
            callback_fn(reconnect_count)

    def emit_diagnostic(self, state: dict[str, Any]) -> None:
        """Emit a diagnostic-state update to registered entities."""
        self.diagnostic_state = dict(state)
        for callback_fn in list(self.callbacks["diagnostic"]):
            callback_fn(self.diagnostic_state)

    @callback
    def add_availability_callback(self, callback_fn: Callable[[bool], None]):
        self.callbacks["availability"].append(callback_fn)
        callback_fn(self.available)
        return lambda: self.callbacks["availability"].remove(callback_fn)

    @callback
    def add_diagnostic_callback(self, callback_fn: Callable[[dict[str, Any]], None]):
        self.callbacks["diagnostic"].append(callback_fn)
        callback_fn(self.diagnostic_state)
        return lambda: self.callbacks["diagnostic"].remove(callback_fn)

    @callback
    def add_measurement_callback(self, callback_fn: Callable[[int, Any], None]):
        self.callbacks["measurement"].append(callback_fn)
        return lambda: self.callbacks["measurement"].remove(callback_fn)

    @callback
    def add_radio_callback(self, callback_fn: Callable[[dict[str, Any]], None]):
        self.callbacks["radio"].append(callback_fn)
        callback_fn(self.last_radio_state)
        return lambda: self.callbacks["radio"].remove(callback_fn)

    @callback
    def add_reconnect_callback(self, callback_fn: Callable[[int], None]):
        self.callbacks["reconnect"].append(callback_fn)
        callback_fn(self.reconnect_count)
        return lambda: self.callbacks["reconnect"].remove(callback_fn)

    @callback
    def add_setpoint_callback(self, callback_fn: Callable[[float], None]):
        self.callbacks["setpoint"].append(callback_fn)
        callback_fn(self.last_setpoint)
        return lambda: self.callbacks["setpoint"].remove(callback_fn)

    @callback
    def add_weather_callback(self, callback_fn: Callable[[dict[str, Any]], None]):
        self.callbacks["weather"].append(callback_fn)
        callback_fn(self.last_weather_state)
        return lambda: self.callbacks["weather"].remove(callback_fn)


async def test_entry_setup_and_unload_with_real_hass_fixture() -> None:
    """Set up and unload the integration through HA's ConfigEntries manager."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        await _assert_entry_setup_and_unload(hass, integration)


async def test_entry_reload_restarts_client_with_real_hass_fixture() -> None:
    """Reload through HA and assert runtime cleanup/startup remains balanced."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        first_client = _FixtureDHEClient()
        second_client = _FixtureDHEClient(last_setpoint=41.0)
        entry = _build_mock_entry(
            host=first_client.host,
            port=first_client.port,
            name="Reload Fixture DHE",
            unique_id="reload-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with patch.object(
            integration,
            "DHEClient",
            side_effect=[first_client, second_client],
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            assert await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()

        assert first_client.stop_called
        assert second_client.start_called
        assert entry.state is ConfigEntryState.LOADED
        assert hass.data[DOMAIN][entry.entry_id].client is second_client
        assert hass.services.has_service(DOMAIN, "search_weather_location")

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert second_client.stop_called
        assert not hass.services.has_service(DOMAIN, "search_weather_location")


async def test_multiple_entries_keep_services_and_unique_ids_separate() -> None:
    """Load two DHE entries and verify service lifetime plus entity IDs."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with async_test_home_assistant() as hass:
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

        with patch.object(
            integration,
            "DHEClient",
            side_effect=[client_one, client_two],
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
    async with async_test_home_assistant() as hass:
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

        with patch.object(
            integration,
            "DHEClient",
            side_effect=[client_one, client_two],
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
    async with async_test_home_assistant() as hass:
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

        with patch.object(integration, "DHEClient", return_value=client):
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


async def test_config_flow_creates_entry_after_pairing_with_real_hass_fixture() -> None:
    """Run setup flow through HA's config-flow manager until entry creation."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(return_value=None)
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
                data={
                    CONF_HOST: "http://dhe-fixture.local/",
                    CONF_PORT: DEFAULT_PORT,
                    CONF_NAME: "Flow Fixture DHE",
                    config_flow.CONF_INTERNAL_SCALD_PROTECTION: "50",
                },
            )

            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "pairing_confirm"
            can_connect.assert_awaited_once_with(
                hass,
                "dhe-fixture.local",
                DEFAULT_PORT,
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={},
            )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "Flow Fixture DHE"
        assert result["data"] == {
            CONF_HOST: "dhe-fixture.local",
            CONF_PORT: DEFAULT_PORT,
            CONF_NAME: "Flow Fixture DHE",
            config_flow.CONF_INTERNAL_SCALD_PROTECTION: "50",
        }
        validate_pairing.assert_awaited_once()
        pairing_args = validate_pairing.await_args.args
        assert pairing_args[:3] == (
            hass,
            "dhe-fixture.local",
            DEFAULT_PORT,
        )
        assert pairing_args[3].endswith("_dhe-fixture.local_8443.txt")


async def test_config_flow_aborts_duplicate_target_with_real_hass_fixture() -> None:
    """Verify HA config flow prevents duplicate normalized DHE targets."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="dhe-duplicate.local",
            port=DEFAULT_PORT,
            name="Existing Fixture DHE",
            unique_id="existing-fixture-dhe",
        )
        entry.add_to_hass(hass)

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_HOST: "http://dhe-duplicate.local/",
                CONF_PORT: DEFAULT_PORT,
                CONF_NAME: "Duplicate Fixture DHE",
                "internal_scald_protection": "50",
            },
        )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"


async def test_options_connection_flow_requires_pairing_for_changed_target_with_real_hass_fixture() -> None:
    """Run connection options through HA's options-flow manager."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="old-dhe.local",
            port=DEFAULT_PORT,
            name="Old Fixture DHE",
            unique_id="old-fixture-dhe",
        )
        entry.add_to_hass(hass)

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(return_value=None)
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            result = await hass.config_entries.options.async_init(entry.entry_id)
            assert result["type"] is FlowResultType.MENU

            result = await hass.config_entries.options.async_configure(
                result["flow_id"],
                user_input={"next_step_id": "connection"},
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "connection"

            result = await hass.config_entries.options.async_configure(
                result["flow_id"],
                user_input={
                    CONF_HOST: "new-dhe.local",
                    CONF_PORT: DEFAULT_PORT,
                    CONF_NAME: "New Fixture DHE",
                    config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55",
                },
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "connection_pairing_confirm"
            can_connect.assert_awaited_once_with(
                hass,
                "new-dhe.local",
                DEFAULT_PORT,
            )

            result = await hass.config_entries.options.async_configure(
                result["flow_id"],
                user_input={},
            )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"] == {
            CONF_HOST: "new-dhe.local",
            CONF_PORT: DEFAULT_PORT,
            CONF_NAME: "New Fixture DHE",
            config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55",
        }
        validate_pairing.assert_awaited_once()


async def test_repair_pairing_button_calls_client_when_enabled_with_real_hass_fixture() -> None:
    """Enable the disabled-by-default repair button and press it through HA."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Repair Fixture DHE",
            unique_id="repair-fixture-dhe",
        )
        entry.add_to_hass(hass)

        registry = er.async_get(hass)
        registry.async_get_or_create(
            "button",
            DOMAIN,
            f"{DOMAIN}_{entry.entry_id}_repair_pairing",
            suggested_object_id="repair_fixture_dhe_repair_pairing",
            disabled_by=None,
        )

        with patch.object(integration, "DHEClient", return_value=client):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        repair_button = _entity_id_for_key(
            hass,
            entry.entry_id,
            "button",
            "repair_pairing",
        )
        state = hass.states.get(repair_button)
        assert state is not None

        client.emit_availability(False)
        await hass.async_block_till_done()
        state = hass.states.get(repair_button)
        assert state is not None
        assert state.state != "unavailable"

        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": repair_button},
            blocking=True,
        )
        assert client.repair_pairing_calls == 1

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_entity_registry_ids_survive_reload_with_real_hass_fixture() -> None:
    """Reload an entry and verify HA keeps the same entity registry IDs."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        first_client = _FixtureDHEClient()
        second_client = _FixtureDHEClient(last_setpoint=41.0)
        entry = _build_mock_entry(
            host=first_client.host,
            port=first_client.port,
            name="Stable Fixture DHE",
            unique_id="stable-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with patch.object(
            integration,
            "DHEClient",
            side_effect=[first_client, second_client],
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            registry = er.async_get(hass)
            before = {
                entity.unique_id: entity.entity_id
                for entity in er.async_entries_for_config_entry(
                    registry,
                    entry.entry_id,
                )
            }

            assert await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()
            after = {
                entity.unique_id: entity.entity_id
                for entity in er.async_entries_for_config_entry(
                    registry,
                    entry.entry_id,
                )
            }

        assert before
        assert before == after
        assert first_client.stop_called
        assert second_client.start_called

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_runtime_callbacks_update_sensor_states_with_real_hass_fixture() -> None:
    """Verify runtime callbacks update real HA sensor entities."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    protocol = importlib.import_module(f"custom_components.{DOMAIN}.protocol")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Runtime Fixture DHE",
            unique_id="runtime-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with patch.object(integration, "DHEClient", return_value=client):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        water_flow_entity = _entity_id_for_key(hass, entry.entry_id, "sensor", "water_flow")
        reconnect_entity = _entity_id_for_key(
            hass,
            entry.entry_id,
            "sensor",
            "reconnect_count",
        )
        connection_state_entity = _entity_id_for_key(
            hass,
            entry.entry_id,
            "sensor",
            "connection_state",
        )

        client.emit_measurement(protocol.ID_WATER_FLOW, 7.5)
        client.emit_reconnect(3)
        client.emit_diagnostic({
            "connection_state": "reconnecting",
            "last_reconnect_reason": "fixture reconnect",
        })
        await hass.async_block_till_done()

        water_flow_state = hass.states.get(water_flow_entity)
        reconnect_state = hass.states.get(reconnect_entity)
        connection_state = hass.states.get(connection_state_entity)

        assert water_flow_state is not None
        assert water_flow_state.state == "7.5"
        assert reconnect_state is not None
        assert reconnect_state.state == "3"
        assert connection_state is not None
        assert connection_state.state == "reconnecting"

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_availability_updates_climate_state_with_real_hass_fixture() -> None:
    """Verify runtime availability callbacks update HA entity state."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Availability Fixture DHE",
            unique_id="availability-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with patch.object(integration, "DHEClient", return_value=client):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        entity_id = "climate.availability_fixture_dhe_water_heating"
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state != "unavailable"

        client.emit_availability(False)
        await hass.async_block_till_done()
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state == "unavailable"

        client.emit_availability(True)
        await hass.async_block_till_done()
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state != "unavailable"
        assert state.attributes["connection_state"] == "connected"

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


def _clear_loaded_integration_modules() -> None:
    """Remove stub-loaded integration modules before HA imports the real package."""
    for module_name in tuple(sys.modules):
        if module_name == "custom_components" or module_name.startswith(
            f"custom_components.{DOMAIN}"
        ):
            sys.modules.pop(module_name)


async def _assert_entry_setup_and_unload(
    hass: HomeAssistant,
    integration: Any,
) -> None:
    """Assert runtime setup and unload against a real Home Assistant instance."""
    client = _FixtureDHEClient()
    entry = _build_mock_entry(
        host=client.host,
        port=client.port,
        name="Fixture DHE",
        unique_id="fixture-dhe",
    )
    entry.add_to_hass(hass)

    with patch.object(integration, "DHEClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert hass.data[DOMAIN][entry.entry_id].client is client
    assert client.start_called
    assert hass.services.has_service(DOMAIN, "search_weather_location")
    assert hass.states.get("climate.fixture_dhe_water_heating") is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert client.stop_called
    assert entry.entry_id not in hass.data.get(DOMAIN, {})
    assert not hass.services.has_service(DOMAIN, "search_weather_location")


def _build_mock_entry(
    *,
    host: str,
    port: int,
    name: str,
    unique_id: str,
) -> MockConfigEntry:
    """Build a DHE config entry for HA fixture tests."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: host,
            CONF_PORT: port,
            CONF_NAME: name,
        },
        title=name,
        unique_id=unique_id,
    )


def _entity_id_for_key(
    hass: HomeAssistant,
    entry_id: str,
    domain: str,
    key: str,
) -> str:
    """Return one entity ID from its stable integration unique-ID key."""
    registry = er.async_get(hass)
    unique_id = f"{DOMAIN}_{entry_id}_{key}"
    for entity in er.async_entries_for_config_entry(registry, entry_id):
        if entity.domain == domain and entity.unique_id == unique_id:
            return entity.entity_id
    raise AssertionError(f"Entity {domain}.{key} not found for entry {entry_id}")
