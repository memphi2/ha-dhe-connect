"""Runtime tests using Home Assistant's real pytest fixtures."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import importlib
from pathlib import Path
import sys
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_test_home_assistant,
)

from homeassistant import loader
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant, callback
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
        self.diagnostic_state: dict[str, Any] = {}
        self.start_called = False
        self.stop_called = False
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
