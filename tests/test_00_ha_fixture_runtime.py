"""Runtime tests using Home Assistant's real pytest fixtures."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import importlib
from ipaddress import ip_address, ip_network
from pathlib import Path
import sys
import types
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_homeassistant_custom_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_test_home_assistant,
)

from homeassistant import config_entries, loader
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)


pytestmark = pytest.mark.asyncio
DOMAIN = "stiebel_dhe_connect"
DEFAULT_PORT = 8443
ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_ZEROCONF_HOST = object()

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from tests.test_fake_dhe_engineio_server import (
        FakeDHEEngineIOServer,
        PAIRING_TOKEN,
        STORED_TOKEN,
    )
except ModuleNotFoundError:
    from test_fake_dhe_engineio_server import (
        FakeDHEEngineIOServer,
        PAIRING_TOKEN,
        STORED_TOKEN,
    )


@pytest.fixture(autouse=True)
def _isolate_discovery_cache():
    """Keep persisted discovery prompts from leaking between HA fixture tests."""
    cache_path = (
        Path(pytest_homeassistant_custom_component.__file__).resolve().parent
        / "testing_config"
        / ".storage"
        / "stiebel_dhe_connect_discovery_cache"
    )
    cache_path.unlink(missing_ok=True)
    yield
    cache_path.unlink(missing_ok=True)


def _schema_defaults(schema: Any) -> dict[str, Any]:
    """Return voluptuous marker defaults from a flow schema."""
    defaults: dict[str, Any] = {}
    for marker in getattr(schema, "schema", {}):
        key = getattr(marker, "schema", None)
        default = getattr(marker, "default", None)
        if callable(default):
            default = default()
        defaults[key] = default
    return defaults


def _schema_suggested_values(schema: Any) -> dict[str, Any]:
    """Return Home Assistant suggested values from a flow schema."""
    suggested_values: dict[str, Any] = {}
    for marker in getattr(schema, "schema", {}):
        key = getattr(marker, "schema", None)
        description = getattr(marker, "description", None) or {}
        if "suggested_value" in description:
            suggested_values[key] = description["suggested_value"]
    return suggested_values


async def _ensure_network_loaded(hass: HomeAssistant) -> None:
    """Load HA's network singleton before aiohttp creates its DNS resolver."""
    network_module = importlib.import_module("homeassistant.components.network")
    async_get_network = getattr(network_module, "async_get_network", None)
    if async_get_network is None:
        network_module = importlib.import_module(
            "homeassistant.components.network.network"
        )
        async_get_network = getattr(network_module, "async_get_network")
    await async_get_network(hass)


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
        self.last_device_info: dict[str, Any] = {}
        self.last_radio_state: dict[str, Any] = {}
        self.last_weather_state: dict[str, Any] = {}
        self.last_wellness_programs: tuple[dict[str, Any], ...] = ()
        self.weather_search_results: list[dict[str, Any]] = []
        self.diagnostic_state: dict[str, Any] = {}
        self.start_called = False
        self.stop_called = False
        self.weather_search_calls: list[tuple[str, int]] = []
        self.weather_add_calls: list[dict[str, Any]] = []
        self.weather_toggle_calls: list[dict[str, Any]] = []
        self.weather_remove_calls: list[dict[str, Any]] = []
        self.weather_select_calls: list[dict[str, Any] | str] = []
        self.bath_fill_target_volume_calls: list[float] = []
        self.eco_mode_calls: list[bool] = []
        self.wellness_program_calls: list[int] = []
        self.stop_wellness_program_calls = 0
        self.radio_play_calls: list[bool] = []
        self.reset_brush_timer_calls = 0
        self.temperature_calls: list[float] = []
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
            "wellness_programs": [],
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

    async def request_measurement_refresh(self, **_kwargs: Any) -> None:
        """Mock a measurement refresh request from the sensor runtime path."""
        return None

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

    async def set_bath_fill_target_volume(self, value: float) -> float:
        """Record a bath fill target volume write."""
        self.bath_fill_target_volume_calls.append(float(value))
        return float(value)

    async def set_eco_mode(self, enabled: bool) -> bool:
        """Record an eco-mode write."""
        self.eco_mode_calls.append(bool(enabled))
        return bool(enabled)

    async def set_wellness_shower_program(self, program_id: int) -> bool:
        """Record a wellness-program start command."""
        self.wellness_program_calls.append(int(program_id))
        return True

    async def stop_wellness_shower_program(self) -> bool:
        """Record a wellness-program stop command."""
        self.stop_wellness_program_calls += 1
        return True

    async def set_radio_play(self, playing: bool) -> bool:
        """Record a radio playback write."""
        self.radio_play_calls.append(bool(playing))
        return bool(playing)

    async def reset_brush_timer(self) -> bool:
        """Record a brush-timer reset call."""
        self.reset_brush_timer_calls += 1
        return True

    async def set_temperature(self, temperature: float) -> float:
        """Record a temperature write."""
        self.temperature_calls.append(float(temperature))
        return float(temperature)

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

    @callback
    def add_wellness_programs_callback(
        self,
        callback_fn: Callable[[tuple[dict[str, Any], ...]], None],
    ):
        self.callbacks["wellness_programs"].append(callback_fn)
        callback_fn(self.last_wellness_programs)
        return lambda: self.callbacks["wellness_programs"].remove(callback_fn)


async def test_entry_setup_and_unload_with_real_hass_fixture() -> None:
    """Set up and unload the integration through HA's ConfigEntries manager."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        await _assert_entry_setup_and_unload(hass, integration)


async def test_async_setup_registers_services_before_entry_load() -> None:
    """Register integration services at domain setup time."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with async_test_home_assistant() as hass:
        assert await integration.async_setup(hass, {})
        assert hass.services.has_service(DOMAIN, "search_weather_location")

        with pytest.raises(HomeAssistantError, match="not loaded"):
            await hass.services.async_call(
                DOMAIN,
                "search_weather_location",
                {"name": "Berlin", "country_id": 49},
                blocking=True,
            )


async def test_entry_setup_raises_not_ready_when_target_unreachable() -> None:
    """Do not set up platforms until the configured DHE endpoint responds."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="offline-dhe.local",
            port=DEFAULT_PORT,
            name="Offline Fixture DHE",
            unique_id="offline-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with patch.object(
            integration,
            "_async_can_connect",
            AsyncMock(return_value=False),
        ):
            with pytest.raises(ConfigEntryNotReady):
                await integration.async_setup_entry(hass, entry)


async def test_entry_setup_falls_back_to_original_data_target() -> None:
    """Use original Zeroconf IP data if an option hostname cannot be reached."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient(host="192.0.2.124", port=DEFAULT_PORT)
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Fallback Fixture DHE",
            unique_id="fallback-fixture-dhe",
        )
        entry.add_to_hass(hass)
        hass.config_entries.async_update_entry(
            entry,
            options={
                CONF_HOST: "dhe-ja06.local",
                CONF_PORT: DEFAULT_PORT,
                CONF_NAME: "Fallback Fixture DHE",
            },
        )

        can_connect = AsyncMock(side_effect=[False, True])
        with (
            patch.object(integration, "DHEClient", return_value=client) as client_cls,
            patch.object(integration, "_async_can_connect", can_connect),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        assert can_connect.await_args_list[0].args == (
            hass,
            "dhe-ja06.local",
            DEFAULT_PORT,
        )
        assert can_connect.await_args_list[1].args == (
            hass,
            "192.0.2.124",
            DEFAULT_PORT,
        )
        assert client_cls.call_args.kwargs["host"] == "192.0.2.124"
        assert client.start_called

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


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

        with (
            patch.object(
                integration,
                "DHEClient",
                side_effect=[first_client, second_client],
            ),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            assert await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()

        assert first_client.stop_called
        assert second_client.start_called
        assert entry.state is ConfigEntryState.LOADED
        assert entry.runtime_data.client is second_client
        assert hass.services.has_service(DOMAIN, "search_weather_location")

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert second_client.stop_called
        assert not hass.services.has_service(DOMAIN, "search_weather_location")


async def test_setup_merges_empty_host_devices_into_stable_entry_device() -> None:
    """Avoid extra HA devices when host/IP identity changes across reconfigure."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        device_registry = dr.async_get(hass)
        client = _FixtureDHEClient(host="dhe-ja06.local", port=DEFAULT_PORT)
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Stable Device Fixture DHE",
            unique_id="aa:bb:cc:dd:ee:ff",
        )
        entry.add_to_hass(hass)

        entity_registry = er.async_get(hass)
        old_ip_device = device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, "192.0.2.124:8443")},
            manufacturer="STIEBEL ELTRON",
            model="DHE Connect",
            name="Old IP DHE",
        )
        entity_registry.async_get_or_create(
            "sensor",
            DOMAIN,
            "legacy_entity_on_ip_device",
            config_entry=entry,
            device_id=old_ip_device.id,
        )
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, "dhe-ja06.local:8443")},
            manufacturer="STIEBEL ELTRON",
            model="DHE Connect",
            name="Old Host DHE",
        )

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        dhe_devices = [
            device
            for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id)
            if any(domain == DOMAIN for domain, _identifier in device.identifiers)
        ]
        assert len(dhe_devices) == 1
        assert (DOMAIN, "device:aa:bb:cc:dd:ee:ff") in dhe_devices[0].identifiers
        assert (DOMAIN, "192.0.2.124:8443") in dhe_devices[0].identifiers
        assert (DOMAIN, "dhe-ja06.local:8443") in dhe_devices[0].identifiers

        migrated_entities = er.async_entries_for_device(
            entity_registry,
            dhe_devices[0].id,
            include_disabled_entities=True,
        )
        assert migrated_entities
        assert any(
            entity.unique_id == "legacy_entity_on_ip_device"
            for entity in migrated_entities
        )

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_runtime_auth_failure_creates_single_repair_issue() -> None:
    """Runtime auth failures create one DHE repair issue without generic reauth."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Auth Failure Fixture DHE",
            unique_id="auth-failure-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        with patch.object(entry, "async_start_reauth") as start_reauth:
            client.emit_diagnostic({"connection_state": "auth_failed"})
            client.emit_diagnostic({"auth_failure": True})
            await hass.async_block_till_done()

        start_reauth.assert_not_called()
        issue_id = repair_issues.pairing_required_issue_id(entry.entry_id)
        reauth_issue_id = f"config_entry_reauth_{DOMAIN}_{entry.entry_id}"
        issue_registry = ir.async_get(hass)
        issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
        assert issue is not None
        assert issue.is_fixable
        assert issue.severity is ir.IssueSeverity.ERROR
        assert issue.translation_key == "pairing_required"
        assert issue.data == {
            "entry_id": entry.entry_id,
            "issue_type": "pairing_required",
        }
        assert issue_registry.async_get_issue("homeassistant", reauth_issue_id) is None
        assert not hass.config_entries.flow.async_progress_by_handler(
            DOMAIN,
            match_context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
        )

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_runtime_auth_failure_does_not_create_duplicate_repair_issues() -> None:
    """Repeated auth-failure diagnostics should not spam duplicate Repairs."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="No Duplicate Repair Fixture DHE",
            unique_id="no-duplicate-repair-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        with patch.object(
            integration,
            "async_create_repair_issue",
            wraps=integration.async_create_repair_issue,
        ) as create_issue:
            client.emit_diagnostic({"connection_state": "auth_failed"})
            client.emit_diagnostic({"connection_state": "auth_failed"})
            client.emit_diagnostic({"auth_failure": True})
            await hass.async_block_till_done()

        assert create_issue.call_count == 1
        issue_id = repair_issues.pairing_required_issue_id(entry.entry_id)
        issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
        assert issue is not None

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_runtime_auth_failure_with_token_reason_creates_token_invalid_issue() -> None:
    """Auth failures with token-specific reason map to token_invalid repairs."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Token Invalid Fixture DHE",
            unique_id="token-invalid-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        client.emit_diagnostic(
            {
                "connection_state": "auth_failed",
                "auth_failure": True,
                "last_reconnect_reason": (
                    "DHEAuthError: stored token is no longer accepted"
                ),
            }
        )
        await hass.async_block_till_done()

        issue_registry = ir.async_get(hass)
        token_issue_id = repair_issues.token_invalid_issue_id(entry.entry_id)
        pairing_issue_id = repair_issues.pairing_required_issue_id(entry.entry_id)
        token_issue = issue_registry.async_get_issue(DOMAIN, token_issue_id)
        assert token_issue is not None
        assert token_issue.translation_key == "token_invalid"
        assert issue_registry.async_get_issue(DOMAIN, pairing_issue_id) is None

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_runtime_connectivity_repairs_respect_grace_and_classify_target() -> None:
    """Do not raise connectivity repairs inside grace; classify host/target hints."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Connectivity Repair Fixture DHE",
            unique_id="connectivity-repair-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        issue_registry = ir.async_get(hass)
        device_issue_id = repair_issues.device_unreachable_issue_id(entry.entry_id)
        host_issue_id = repair_issues.host_changed_or_unreachable_issue_id(
            entry.entry_id
        )
        token_issue_id = repair_issues.token_invalid_issue_id(entry.entry_id)

        client.emit_diagnostic(
            {
                "connection_state": "reconnecting",
                "should_mark_unavailable": False,
                "last_reconnect_reason": "ServerDisconnectedError: socket closed",
            }
        )
        await hass.async_block_till_done()
        assert issue_registry.async_get_issue(DOMAIN, device_issue_id) is None
        assert issue_registry.async_get_issue(DOMAIN, host_issue_id) is None

        client.emit_diagnostic(
            {
                "connection_state": "reconnecting",
                "should_mark_unavailable": True,
                "last_reconnect_reason": "ServerDisconnectedError: socket closed",
            }
        )
        await hass.async_block_till_done()
        assert issue_registry.async_get_issue(DOMAIN, device_issue_id) is not None
        assert issue_registry.async_get_issue(DOMAIN, host_issue_id) is None

        client.emit_diagnostic(
            {
                "connection_state": "reconnecting",
                "should_mark_unavailable": True,
                "last_reconnect_reason": (
                    "ClientConnectorError: name or service not known"
                ),
            }
        )
        await hass.async_block_till_done()
        assert issue_registry.async_get_issue(DOMAIN, host_issue_id) is not None
        assert issue_registry.async_get_issue(DOMAIN, device_issue_id) is None
        assert issue_registry.async_get_issue(DOMAIN, token_issue_id) is None

        client.emit_diagnostic(
            {
                "connection_state": "reconnecting",
                "should_mark_unavailable": True,
                "last_reconnect_reason": (
                    'DHEError: GET 400: {"code":400,"message":"Session ID unknown"}'
                ),
            }
        )
        await hass.async_block_till_done()
        assert issue_registry.async_get_issue(DOMAIN, token_issue_id) is not None
        assert issue_registry.async_get_issue(DOMAIN, host_issue_id) is None
        assert issue_registry.async_get_issue(DOMAIN, device_issue_id) is None

        client.emit_diagnostic({"connection_state": "initializing"})
        await hass.async_block_till_done()
        assert issue_registry.async_get_issue(DOMAIN, host_issue_id) is None
        assert issue_registry.async_get_issue(DOMAIN, token_issue_id) is not None

        client.emit_diagnostic({"connection_state": "connected"})
        await hass.async_block_till_done()
        assert issue_registry.async_get_issue(DOMAIN, token_issue_id) is None

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_runtime_discovery_conflict_repair_issue_lifecycle() -> None:
    """Discovery-conflict repair issue is created and cleared on recovery."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Discovery Conflict Fixture DHE",
            unique_id="discovery-conflict-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        issue_id = repair_issues.discovery_conflict_issue_id(entry.entry_id)
        issue_registry = ir.async_get(hass)
        client.emit_diagnostic(
            {
                "connection_state": "reconnecting",
                "discovery_conflict": True,
            }
        )
        await hass.async_block_till_done()
        issue = issue_registry.async_get_issue(DOMAIN, issue_id)
        assert issue is not None
        assert issue.translation_key == "discovery_conflict"

        client.emit_diagnostic({"connection_state": "connected"})
        await hass.async_block_till_done()
        assert issue_registry.async_get_issue(DOMAIN, issue_id) is None

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_runtime_stored_token_pairing_prompt_creates_single_repair_issue() -> None:
    """A deleted DHE token must become one HA repair, not a silent pairing prompt."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    protocol = importlib.import_module(f"custom_components.{DOMAIN}.protocol")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    token_file_helpers = importlib.import_module(
        f"custom_components.{DOMAIN}.token_file_helpers"
    )
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        await _ensure_network_loaded(hass)
        async with FakeDHEEngineIOServer(protocol.NS) as server:
            token_file = Path(
                hass.config.path(
                    token_file_helpers.token_file_for_target(
                        server.host,
                        server.port,
                    )
                )
            )
            token_file.parent.mkdir(parents=True, exist_ok=True)
            token_file.write_text(STORED_TOKEN, encoding="utf-8")
            server.queue_pairing_request()

            entry = _build_mock_entry(
                host=server.host,
                port=server.port,
                name="Stored Token Deleted Fixture DHE",
                unique_id="stored-token-deleted-fixture-dhe",
            )
            entry.add_to_hass(hass)
            with patch.object(
                integration,
                "_async_can_connect",
                AsyncMock(return_value=True),
            ):
                assert await hass.config_entries.async_setup(entry.entry_id)

            pairing_issue_id = repair_issues.pairing_required_issue_id(entry.entry_id)
            token_issue_id = repair_issues.token_invalid_issue_id(entry.entry_id)
            reauth_issue_id = f"config_entry_reauth_{DOMAIN}_{entry.entry_id}"
            issue_registry = ir.async_get(hass)
            issue = None
            for _attempt in range(40):
                await hass.async_block_till_done()
                issue = issue_registry.async_get_issue(
                    DOMAIN, token_issue_id
                ) or issue_registry.async_get_issue(DOMAIN, pairing_issue_id)
                if issue is not None:
                    break
                await asyncio.sleep(0.05)

            assert issue is not None
            assert issue.translation_key in {"token_invalid", "pairing_required"}
            assert issue_registry.async_get_issue("homeassistant", reauth_issue_id) is None
            assert not hass.config_entries.flow.async_progress_by_handler(
                DOMAIN,
                match_context={
                    "source": config_entries.SOURCE_REAUTH,
                    "entry_id": entry.entry_id,
                },
            )
            assert token_file.read_text(encoding="utf-8") == STORED_TOKEN

            assert await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()


async def test_runtime_connected_deletes_stale_reauth_issues() -> None:
    """Successful runtime recovery clears stale DHE and HA reauth issues."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Recovered Fixture DHE",
            unique_id="recovered-fixture-dhe",
        )
        entry.add_to_hass(hass)
        issue_id = repair_issues.pairing_required_issue_id(entry.entry_id)
        reauth_issue_id = f"config_entry_reauth_{DOMAIN}_{entry.entry_id}"
        issue_registry = ir.async_get(hass)
        repair_issues.async_create_pairing_issue(hass, entry.entry_id, entry.title)
        ir.async_create_issue(
            hass,
            "homeassistant",
            reauth_issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="config_entry_reauth",
        )
        assert issue_registry.async_get_issue(DOMAIN, issue_id) is not None
        assert issue_registry.async_get_issue("homeassistant", reauth_issue_id) is not None

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        assert issue_registry.async_get_issue(DOMAIN, issue_id) is None
        assert issue_registry.async_get_issue("homeassistant", reauth_issue_id) is None

        repair_issues.async_create_pairing_issue(hass, entry.entry_id, entry.title)
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
                "title_placeholders": {"name": entry.title},
                "unique_id": entry.unique_id,
            },
            data=dict(entry.data),
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"
        ir.async_create_issue(
            hass,
            "homeassistant",
            reauth_issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="config_entry_reauth",
        )
        entity_registry = er.async_get(hass)
        saving_entity = next(
            entity
            for entity in er.async_entries_for_config_entry(
                entity_registry,
                entry.entry_id,
            )
            if entity.translation_key == "odb_possible_energy_saving"
        )
        statistic_issue_id = f"mean_type_changed_{saving_entity.entity_id}"
        ir.async_create_issue(
            hass,
            "sensor",
            statistic_issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="mean_type_changed",
        )
        assert issue_registry.async_get_issue(DOMAIN, issue_id) is not None
        assert issue_registry.async_get_issue("homeassistant", reauth_issue_id) is not None
        assert issue_registry.async_get_issue("sensor", statistic_issue_id) is not None
        assert hass.config_entries.flow.async_progress_by_handler(
            DOMAIN,
            match_context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
        )

        client.emit_diagnostic({"connection_state": "initializing"})
        assert issue_registry.async_get_issue(DOMAIN, issue_id) is not None
        assert issue_registry.async_get_issue("homeassistant", reauth_issue_id) is not None
        assert issue_registry.async_get_issue("sensor", statistic_issue_id) is not None
        client.emit_diagnostic({"connection_state": "connected"})
        await hass.async_block_till_done()

        assert issue_registry.async_get_issue(DOMAIN, issue_id) is None
        assert issue_registry.async_get_issue("homeassistant", reauth_issue_id) is None
        assert issue_registry.async_get_issue("sensor", statistic_issue_id) is None
        assert not hass.config_entries.flow.async_progress_by_handler(
            DOMAIN,
            match_context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
        )

        repair_issues.async_create_pairing_issue(hass, entry.entry_id, entry.title)
        assert issue_registry.async_get_issue(DOMAIN, issue_id) is None
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key="pairing_required",
            data={"entry_id": entry.entry_id},
        )
        assert issue_registry.async_get_issue(DOMAIN, issue_id) is not None
        client.emit_diagnostic({"connection_state": "connected"})
        await hass.async_block_till_done()
        assert issue_registry.async_get_issue(DOMAIN, issue_id) is None

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


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

        with (
            patch.object(
                integration,
                "DHEClient",
                side_effect=[client_one, client_two],
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

        with (
            patch.object(
                integration,
                "DHEClient",
                side_effect=[client_one, client_two],
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
    async with async_test_home_assistant() as hass:
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
    async with async_test_home_assistant() as hass:
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


async def test_config_flow_creates_entry_after_pairing_with_real_hass_fixture() -> None:
    """Run setup flow through HA's config-flow manager until entry creation."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(
            return_value=config_flow.SetupPairingResult(
                unique_id="aa:bb:cc:dd:ee:ff",
            )
        )
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
        assert result["result"].unique_id == "aa:bb:cc:dd:ee:ff"
        validate_pairing.assert_awaited_once()
        pairing_args = validate_pairing.await_args.args
        assert pairing_args[:3] == (
            hass,
            "dhe-fixture.local",
            DEFAULT_PORT,
        )
        assert pairing_args[3].endswith("_dhe-fixture.local_8443.txt")


async def test_repairs_flow_keeps_issue_when_dhe_is_unreachable() -> None:
    """Keep a Repairs issue open when the DHE cannot be reached."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    repairs = importlib.import_module(f"custom_components.{DOMAIN}.repairs")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="repair-offline-dhe.local",
            port=DEFAULT_PORT,
            name="Repair Offline Fixture DHE",
            unique_id="repair-offline-fixture-dhe",
        )
        entry.add_to_hass(hass)
        repair_issues.async_create_pairing_issue(hass, entry.entry_id, entry.title)
        issue_id = repair_issues.pairing_required_issue_id(entry.entry_id)
        issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
        assert issue is not None

        can_connect = AsyncMock(return_value=False)
        validate_pairing = AsyncMock(return_value=config_flow.SetupPairingResult())
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            repair_flow = await repairs.async_create_fix_flow(
                hass,
                issue_id,
                issue.data,
            )
            repair_flow.hass = hass
            repair_flow.handler = DOMAIN
            repair_flow.flow_id = "repair-offline-flow-id"
            repair_flow.context = {}
            repair_flow.init_data = {"issue_id": issue_id}

            result = await repair_flow.async_step_confirm({})

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "confirm"
        assert result["errors"]["base"] == "cannot_connect"
        can_connect.assert_awaited_once_with(
            hass,
            "repair-offline-dhe.local",
            DEFAULT_PORT,
        )
        validate_pairing.assert_not_awaited()
        assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None


async def test_repairs_flow_keeps_issue_when_pairing_validation_fails() -> None:
    """Surface pairing errors from a Repairs flow without closing the issue."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    repairs = importlib.import_module(f"custom_components.{DOMAIN}.repairs")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="repair-pairing-error-dhe.local",
            port=DEFAULT_PORT,
            name="Repair Pairing Error Fixture DHE",
            unique_id="repair-pairing-error-fixture-dhe",
        )
        entry.add_to_hass(hass)
        repair_issues.async_create_pairing_issue(hass, entry.entry_id, entry.title)
        issue_id = repair_issues.pairing_required_issue_id(entry.entry_id)
        issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
        assert issue is not None

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(
            return_value=config_flow.SetupPairingResult(error_key="pairing_timeout")
        )
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            repair_flow = await repairs.async_create_fix_flow(
                hass,
                issue_id,
                issue.data,
            )
            repair_flow.hass = hass
            repair_flow.handler = DOMAIN
            repair_flow.flow_id = "repair-pairing-error-flow-id"
            repair_flow.context = {}
            repair_flow.init_data = {"issue_id": issue_id}

            result = await repair_flow.async_step_confirm({})

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "confirm"
        assert result["errors"]["base"] == "pairing_timeout"
        can_connect.assert_awaited_once_with(
            hass,
            "repair-pairing-error-dhe.local",
            DEFAULT_PORT,
        )
        validate_pairing.assert_awaited_once()
        assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None


async def test_repairs_flow_aborts_when_issue_entry_is_missing() -> None:
    """Abort a stale Repairs issue whose config entry was removed."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    repairs = importlib.import_module(f"custom_components.{DOMAIN}.repairs")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with async_test_home_assistant() as hass:
        missing_entry_id = "missing-repair-entry"
        issue_id = repair_issues.pairing_required_issue_id(missing_entry_id)
        repair_flow = await repairs.async_create_fix_flow(
            hass,
            issue_id,
            {"entry_id": missing_entry_id},
        )
        repair_flow.hass = hass
        repair_flow.handler = DOMAIN
        repair_flow.flow_id = "missing-repair-flow-id"
        repair_flow.context = {}
        repair_flow.init_data = {"issue_id": issue_id}

        result = await repair_flow.async_step_init()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "entry_not_found"


async def test_repairs_flow_rejects_mismatched_issue_data() -> None:
    """Reject Repairs issue IDs whose embedded entry ID does not match data."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    repairs = importlib.import_module(f"custom_components.{DOMAIN}.repairs")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with async_test_home_assistant() as hass:
        issue_id = repair_issues.pairing_required_issue_id("entry-a")
        with pytest.raises(ValueError, match="does not match"):
            await repairs.async_create_fix_flow(
                hass,
                issue_id,
                {"entry_id": "entry-b"},
            )


async def test_reauth_flow_repairs_pairing_with_real_hass_fixture() -> None:
    """Run HA reauth flow and verify it validates a fresh DHE pairing."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="reauth-dhe.local",
            port=DEFAULT_PORT,
            name="Reauth Fixture DHE",
            unique_id="reauth-fixture-dhe",
        )
        entry.add_to_hass(hass)
        repair_issues.async_create_pairing_issue(hass, entry.entry_id, entry.title)
        issue_id = repair_issues.pairing_required_issue_id(entry.entry_id)
        assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(return_value=config_flow.SetupPairingResult())
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_REAUTH,
                    "entry_id": entry.entry_id,
                },
                data=dict(entry.data),
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "reauth_confirm"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={},
            )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reauth_successful"
        can_connect.assert_awaited_once_with(hass, "reauth-dhe.local", DEFAULT_PORT)
        validate_pairing.assert_awaited_once()
        assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_repairs_flow_validates_fresh_pairing_with_real_hass_fixture() -> None:
    """Run the fixable Repairs issue through the DHE pairing validation path."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    repairs = importlib.import_module(f"custom_components.{DOMAIN}.repairs")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="repair-flow-dhe.local",
            port=DEFAULT_PORT,
            name="Repair Flow Fixture DHE",
            unique_id="repair-flow-fixture-dhe",
        )
        entry.add_to_hass(hass)
        repair_issues.async_create_pairing_issue(hass, entry.entry_id, entry.title)
        issue_id = repair_issues.pairing_required_issue_id(entry.entry_id)
        issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
        assert issue is not None

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(return_value=config_flow.SetupPairingResult())
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            repair_flow = await repairs.async_create_fix_flow(
                hass,
                issue_id,
                issue.data,
            )
            repair_flow.hass = hass
            repair_flow.handler = DOMAIN
            repair_flow.flow_id = "repair-flow-id"
            repair_flow.context = {}
            repair_flow.init_data = {"issue_id": issue_id}

            result = await repair_flow.async_step_init()
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "confirm"

            result = await repair_flow.async_step_confirm({})

        assert result["type"] is FlowResultType.CREATE_ENTRY
        can_connect.assert_awaited_once_with(
            hass,
            "repair-flow-dhe.local",
            DEFAULT_PORT,
        )
        validate_pairing.assert_awaited_once()
        assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_repairs_flow_success_reloads_existing_entry_without_duplication() -> None:
    """Successful repair reloads the same entry and keeps one device structure."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    repairs = importlib.import_module(f"custom_components.{DOMAIN}.repairs")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Repair Reload Fixture DHE",
            unique_id="repair-reload-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        entry_count_before = len(hass.config_entries.async_entries(DOMAIN))
        device_count_before = len(
            dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
        )

        repair_issues.async_create_pairing_issue(hass, entry.entry_id, entry.title)
        issue_id = repair_issues.pairing_required_issue_id(entry.entry_id)
        issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
        assert issue is not None

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(return_value=config_flow.SetupPairingResult())
        reload_entry = AsyncMock(return_value=True)
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
            patch.object(hass.config_entries, "async_reload", reload_entry),
        ):
            repair_flow = await repairs.async_create_fix_flow(
                hass,
                issue_id,
                issue.data,
            )
            repair_flow.hass = hass
            repair_flow.handler = DOMAIN
            repair_flow.flow_id = "repair-reload-flow-id"
            repair_flow.context = {}
            repair_flow.init_data = {"issue_id": issue_id}

            result = await repair_flow.async_step_confirm({})

        assert result["type"] is FlowResultType.CREATE_ENTRY
        can_connect.assert_awaited_once_with(hass, client.host, client.port)
        validate_pairing.assert_awaited_once()
        reload_entry.assert_awaited_once_with(entry.entry_id)
        assert len(hass.config_entries.async_entries(DOMAIN)) == entry_count_before
        assert (
            len(dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id))
            == device_count_before
        )
        assert entry.unique_id == "repair-reload-fixture-dhe"
        assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_token_invalid_repairs_flow_reuses_pairing_validation_path() -> None:
    """token_invalid issues must use the same pairing repair flow."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    repairs = importlib.import_module(f"custom_components.{DOMAIN}.repairs")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="token-flow-dhe.local",
            port=DEFAULT_PORT,
            name="Token Flow Fixture DHE",
            unique_id="token-flow-fixture-dhe",
        )
        entry.add_to_hass(hass)
        repair_issues.async_create_repair_issue(
            hass,
            entry.entry_id,
            repair_issues.TOKEN_INVALID_ISSUE,
            entry.title,
        )
        issue_id = repair_issues.token_invalid_issue_id(entry.entry_id)
        issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
        assert issue is not None

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(return_value=config_flow.SetupPairingResult())
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            repair_flow = await repairs.async_create_fix_flow(
                hass,
                issue_id,
                issue.data,
            )
            repair_flow.hass = hass
            repair_flow.handler = DOMAIN
            repair_flow.flow_id = "token-repair-flow-id"
            repair_flow.context = {}
            repair_flow.init_data = {"issue_id": issue_id}

            result = await repair_flow.async_step_init()
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "confirm"

            result = await repair_flow.async_step_confirm({})

        assert result["type"] is FlowResultType.CREATE_ENTRY
        can_connect.assert_awaited_once_with(
            hass,
            "token-flow-dhe.local",
            DEFAULT_PORT,
        )
        validate_pairing.assert_awaited_once()
        assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_config_flow_scan_choice_prefills_manual_form_with_real_hass_fixture() -> None:
    """Run optional setup scan progress before the manual setup form."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        scan = AsyncMock(
            return_value=[
                types.SimpleNamespace(
                    host="192.0.2.124",
                    port=DEFAULT_PORT,
                    evidence=("STE DHE App",),
                )
            ]
        )
        with (
            patch.object(config_flow, "async_scan_dhe_hosts", scan),
            patch.object(
                config_flow,
                "local_ipv4_addresses_from_hass",
                return_value=["192.168.50.10"],
            ),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "user"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {config_flow.CONF_SETUP_MODE: config_flow.SETUP_MODE_SCAN},
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "subnet_scan"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    config_flow.CONF_SCAN_SUBNET_MODE: (
                        config_flow.SCAN_SUBNET_MODE_NETWORK_MASK
                    )
                },
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "subnet_scan_network_mask"
            suggested = _schema_suggested_values(result["data_schema"])
            assert suggested[config_flow.CONF_SCAN_NETWORK_ADDRESS] == "192.168.50.0"
            assert suggested[config_flow.CONF_SCAN_NETMASK] == "255.255.255.0"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    config_flow.CONF_SCAN_NETWORK_ADDRESS: "192.168.50.0",
                    config_flow.CONF_SCAN_NETMASK: "255.255.255.0",
                },
            )
            assert result["type"] is FlowResultType.SHOW_PROGRESS
            assert result["progress_action"] == "scan_dhe"

            await hass.async_block_till_done()
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
            )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "manual"
        defaults = _schema_defaults(result["data_schema"])
        assert defaults[CONF_HOST] == "192.0.2.124"
        assert defaults[CONF_PORT] == DEFAULT_PORT
        scan.assert_awaited_once_with(
            hass,
            networks=[ip_network("192.168.50.0/24")],
            port=DEFAULT_PORT,
        )


async def test_config_flow_current_subnet_scan_progress_with_real_hass_fixture() -> None:
    """Exercise HA config-flow progress handling for the current-subnet scan."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        scan = AsyncMock(return_value=[])
        with patch.object(config_flow, "async_scan_dhe_hosts", scan):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "user"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {config_flow.CONF_SETUP_MODE: config_flow.SETUP_MODE_SCAN},
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "subnet_scan"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    config_flow.CONF_SCAN_SUBNET_MODE: (
                        config_flow.SCAN_SUBNET_MODE_CURRENT
                    ),
                    config_flow.CONF_SCAN_PORT: DEFAULT_PORT,
                },
            )
            assert result["type"] is FlowResultType.SHOW_PROGRESS
            assert result["step_id"] == "network_scan"
            assert result["progress_action"] == "scan_dhe"

            await hass.async_block_till_done()
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "manual"

        defaults = _schema_defaults(result["data_schema"])
        assert defaults[CONF_PORT] == DEFAULT_PORT
        assert "host" not in defaults or defaults[CONF_HOST] in (None, "")
        assert "No DHE" in result["description_placeholders"]["scan_status"]
        scan.assert_awaited_once_with(hass, networks=None, port=DEFAULT_PORT)


async def test_scan_prefilled_flow_uses_pairing_unique_id_with_real_hass_fixture() -> None:
    """Create a scanned entry with the same MAC unique-id path as Zeroconf."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        scan = AsyncMock(
            return_value=[
                types.SimpleNamespace(
                    host="192.0.2.124",
                    port=DEFAULT_PORT,
                    evidence=("STE DHE App",),
                )
            ]
        )
        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(
            return_value=config_flow.SetupPairingResult(
                unique_id="aa:bb:cc:dd:ee:ff",
            )
        )
        with (
            patch.object(config_flow, "async_scan_dhe_hosts", scan),
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {config_flow.CONF_SETUP_MODE: config_flow.SETUP_MODE_SCAN},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    config_flow.CONF_SCAN_SUBNET_MODE: (
                        config_flow.SCAN_SUBNET_MODE_CURRENT
                    )
                },
            )
            assert result["type"] is FlowResultType.SHOW_PROGRESS

            await hass.async_block_till_done()
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "manual"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    CONF_HOST: "192.0.2.124",
                    CONF_PORT: DEFAULT_PORT,
                    CONF_NAME: "Scanned DHE",
                    config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55",
                },
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "pairing_confirm"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {},
            )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["result"].unique_id == "aa:bb:cc:dd:ee:ff"
        assert result["data"][CONF_HOST] == "192.0.2.124"
        scan.assert_awaited_once()
        can_connect.assert_awaited_once_with(hass, "192.0.2.124", DEFAULT_PORT)
        validate_pairing.assert_awaited_once()


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


async def test_zeroconf_flow_collects_tmax_then_creates_entry_after_pairing() -> None:
    """Run Zeroconf setup without creating an entry before pairing succeeds."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(
            return_value=config_flow.SetupPairingResult(
                unique_id="aa:bb:cc:dd:ee:ff",
            )
        )
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info("DHE-JA06.local.", DEFAULT_PORT),
            )

            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "zeroconf_confirm"
            defaults = _schema_defaults(result["data_schema"])
            assert defaults == {config_flow.CONF_INTERNAL_SCALD_PROTECTION: "60"}
            assert hass.config_entries.async_entries(DOMAIN) == []

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55"},
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "pairing_confirm"
            assert hass.config_entries.async_entries(DOMAIN) == []

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={},
            )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "DHE-JA06"
        assert result["data"] == {
            CONF_HOST: "192.0.2.124",
            CONF_PORT: DEFAULT_PORT,
            CONF_NAME: "DHE-JA06",
            config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55",
        }
        assert result["result"].unique_id == "aa:bb:cc:dd:ee:ff"
        can_connect.assert_awaited_once_with(hass, "192.0.2.124", DEFAULT_PORT)
        validate_pairing.assert_awaited_once()


async def test_zeroconf_flow_pairs_against_fake_dhe_engineio_server() -> None:
    """Run Zeroconf -> Tmax -> pairing -> entry creation against Fake-DHE."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    client_pairing = importlib.import_module(
        f"custom_components.{DOMAIN}.client_pairing"
    )
    protocol = importlib.import_module(f"custom_components.{DOMAIN}.protocol")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        await _ensure_network_loaded(hass)
        async with FakeDHEEngineIOServer(protocol.NS) as server:
            server.queue_pairing_request()
            server.queue_pairing_result(True)
            server.queue_token_response(PAIRING_TOKEN)
            server.queue_authentication()
            server.queue_device_info()

            with (
                patch.object(client_pairing.persistent_notification, "async_create"),
                patch.object(client_pairing.persistent_notification, "async_dismiss"),
            ):
                result = await hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": config_entries.SOURCE_ZEROCONF},
                    data=_zeroconf_info(
                        "DHE-JA06.local.",
                        server.port,
                        host=server.host,
                        ip=server.host,
                    ),
                )

                assert result["type"] is FlowResultType.FORM
                assert result["step_id"] == "zeroconf_confirm"
                assert hass.config_entries.async_entries(DOMAIN) == []

                result = await hass.config_entries.flow.async_configure(
                    result["flow_id"],
                    user_input={config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55"},
                )
                assert result["type"] is FlowResultType.FORM
                assert result["step_id"] == "pairing_confirm"

                result = await hass.config_entries.flow.async_configure(
                    result["flow_id"],
                    user_input={},
                )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "DHE-JA06"
        assert result["data"][CONF_HOST] == server.host
        assert result["data"][CONF_PORT] == server.port
        assert result["data"][config_flow.CONF_INTERNAL_SCALD_PROTECTION] == "55"
        assert result["result"].unique_id == "aa:bb:cc:dd:ee:ff"
        assert any(
            '"token":""' in packet and '["token_request"' in packet
            for packet in server.posted_packets
        )
        assert any(PAIRING_TOKEN in packet for packet in server.posted_packets)


@pytest.mark.parametrize(
    ("discovery_kwargs", "expected_host", "expected_port", "expected_title"),
    [
        (
            {
                "hostname": "dhe-ja06.local.",
                "port": DEFAULT_PORT,
                "host": "dhe-ja06.local.",
                "name": "DHE Connect DHE-JA06._ste-dhe._tcp.local.",
            },
            "dhe-ja06.local",
            DEFAULT_PORT,
            "DHE Connect DHE-JA06",
        ),
        (
            {"hostname": "dhe-ja06.local.", "port": DEFAULT_PORT, "host": None},
            "dhe-ja06.local",
            DEFAULT_PORT,
            "dhe-ja06",
        ),
        (
            {
                "hostname": "dhe-ja06.local.",
                "port": DEFAULT_PORT,
                "host": "192.0.2.125",
                "name": "DHE-JA06.local.",
                "ip": "192.0.2.125",
            },
            "192.0.2.125",
            DEFAULT_PORT,
            "DHE-JA06",
        ),
        (
            {
                "hostname": "dhe-ja06.local.",
                "port": DEFAULT_PORT,
                "host": "192.0.2.126",
                "name": "DHE-JA06._ste-dhe._tcp.local.",
                "ip": "192.0.2.126",
            },
            "192.0.2.126",
            DEFAULT_PORT,
            "DHE-JA06",
        ),
        (
            {
                "hostname": None,
                "port": DEFAULT_PORT,
                "host": "192.0.2.127",
                "name": "DHE-JA06.local.",
                "ip": "192.0.2.127",
            },
            "192.0.2.127",
            DEFAULT_PORT,
            "DHE-JA06",
        ),
        (
            {
                "hostname": "dhe-ja06.local.",
                "port": None,
                "host": "192.0.2.128",
                "ip": "192.0.2.128",
            },
            "192.0.2.128",
            DEFAULT_PORT,
            "dhe-ja06",
        ),
    ],
)
async def test_zeroconf_flow_accepts_realistic_discovery_payload_variants(
    discovery_kwargs: dict[str, Any],
    expected_host: str,
    expected_port: int,
    expected_title: str,
) -> None:
    """Verify real-world mDNS payload shapes normalize to one setup path."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(
            return_value=config_flow.SetupPairingResult(
                unique_id=f"unique-{expected_host}",
            )
        )
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info(**discovery_kwargs),
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "zeroconf_confirm"
            can_connect.assert_awaited_once_with(hass, expected_host, expected_port)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55"},
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "pairing_confirm"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={},
            )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == expected_title
        assert result["data"][CONF_HOST] == expected_host
        assert result["data"][CONF_PORT] == expected_port
        validate_pairing.assert_awaited_once()


@pytest.mark.parametrize(
    "port",
    ["not-a-port", 0, -1, 65536],
)
async def test_zeroconf_flow_aborts_invalid_port_payload(port: Any) -> None:
    """Reject discovery payloads that do not contain a usable TCP port."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        can_connect = AsyncMock(return_value=True)
        with patch.object(config_flow, "_can_connect", can_connect):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info("dhe-ja06.local.", port),
            )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "invalid_discovery_parameters"
        can_connect.assert_not_awaited()


async def test_zeroconf_conflict_creates_and_clears_discovery_repair_issue() -> None:
    """A hard Zeroconf identity conflict should raise and later clear a repair issue."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        issue_registry = ir.async_get(hass)
        conflict_host = "192.0.2.140"
        issue_id = config_flow._discovery_conflict_issue_id(conflict_host, DEFAULT_PORT)

        first = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=_zeroconf_info(
                "dhe-ja06.local.",
                DEFAULT_PORT,
                host=conflict_host,
                ip="192.0.2.141",
                name="DHE Connect DHE-JA06._ste-dhe._tcp.local.",
            ),
        )
        assert first["type"] is FlowResultType.ABORT
        assert first["reason"] == "conflicting_discovery_identity"
        issue = issue_registry.async_get_issue(DOMAIN, issue_id)
        assert issue is not None
        assert issue.translation_key == "discovery_conflict"

        can_connect = AsyncMock(return_value=True)
        with patch.object(config_flow, "_can_connect", can_connect):
            second = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info(
                    "dhe-ja06.local.",
                    DEFAULT_PORT,
                    host=conflict_host,
                    ip=conflict_host,
                    name="DHE Connect DHE-JA06._ste-dhe._tcp.local.",
                ),
            )
        assert second["type"] is FlowResultType.FORM
        assert second["step_id"] == "zeroconf_confirm"
        assert issue_registry.async_get_issue(DOMAIN, issue_id) is None


async def test_user_flow_can_select_in_progress_zeroconf_discovery() -> None:
    """Run Add Device through the visible Zeroconf/scan/manual choice."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(
            return_value=config_flow.SetupPairingResult(
                unique_id="aa:bb:cc:dd:ee:ff",
            )
        )
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            zeroconf = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info("DHE-JA06.local.", DEFAULT_PORT),
            )
            assert zeroconf["type"] is FlowResultType.FORM
            assert zeroconf["step_id"] == "zeroconf_confirm"

            user = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )
            assert user["type"] is FlowResultType.FORM
            assert user["step_id"] == "user"
            defaults = _schema_defaults(user["data_schema"])
            assert (
                defaults[config_flow.CONF_SETUP_MODE]
                == config_flow.SETUP_MODE_SCAN
            )

            result = await hass.config_entries.flow.async_configure(
                user["flow_id"],
                user_input={
                    config_flow.CONF_SETUP_MODE: "zeroconf:192.0.2.124:8443",
                },
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "zeroconf_confirm"
            progress = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
            assert all(flow["flow_id"] != zeroconf["flow_id"] for flow in progress)
            assert any(flow["flow_id"] == result["flow_id"] for flow in progress)

            duplicate = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info("DHE-JA06.local.", DEFAULT_PORT),
            )
            assert duplicate["type"] is FlowResultType.ABORT
            assert duplicate["reason"] == "already_in_progress"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55"},
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "pairing_confirm"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={},
            )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "DHE-JA06"
        assert result["data"][CONF_HOST] == "192.0.2.124"
        assert result["result"].unique_id == "aa:bb:cc:dd:ee:ff"
        assert can_connect.await_count == 2
        validate_pairing.assert_awaited_once()


async def test_user_zeroconf_takeover_keeps_source_flow_on_connect_failure() -> None:
    """Keep the original discovery setup path when takeover cannot connect."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        can_connect = AsyncMock(side_effect=[True, False])
        with patch.object(config_flow, "_can_connect", can_connect):
            zeroconf = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info("DHE-JA06.local.", DEFAULT_PORT),
            )
            assert zeroconf["type"] is FlowResultType.FORM
            assert zeroconf["step_id"] == "zeroconf_confirm"

            user = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )
            result = await hass.config_entries.flow.async_configure(
                user["flow_id"],
                user_input={
                    config_flow.CONF_SETUP_MODE: "zeroconf:192.0.2.124:8443",
                },
            )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "cannot_connect"
        assert can_connect.await_count == 2
        progress = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        assert any(flow["flow_id"] == zeroconf["flow_id"] for flow in progress)


async def test_zeroconf_flow_aborts_duplicate_host_port() -> None:
    """Verify Zeroconf discovery does not start for an existing DHE target."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="192.0.2.124",
            port=DEFAULT_PORT,
            name="Existing DHE",
            unique_id="existing-fixture-dhe",
        )
        entry.add_to_hass(hass)

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=_zeroconf_info("DHE-JA06.local.", DEFAULT_PORT),
        )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"


async def test_zeroconf_pairing_aborts_duplicate_mac_after_host_ip_mismatch() -> None:
    """Abort when Zeroconf finds an existing manual entry through another host."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="dhe-ja06.local",
            port=DEFAULT_PORT,
            name="Existing DHE",
            unique_id="aa:bb:cc:dd:ee:ff",
        )
        entry.add_to_hass(hass)

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(
            return_value=config_flow.SetupPairingResult(
                unique_id="aa:bb:cc:dd:ee:ff",
            )
        )
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info(
                    "dhe-ja06.local.",
                    DEFAULT_PORT,
                    host="192.0.2.124",
                ),
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "zeroconf_confirm"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55"},
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "pairing_confirm"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={},
            )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"
        assert len(hass.config_entries.async_entries(DOMAIN)) == 1
        can_connect.assert_awaited_once_with(hass, "192.0.2.124", DEFAULT_PORT)
        validate_pairing.assert_awaited_once()


async def test_zeroconf_flow_aborts_matching_flow_already_in_progress() -> None:
    """Verify duplicate Zeroconf discoveries share one setup flow."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        with patch.object(config_flow, "_can_connect", AsyncMock(return_value=True)):
            first = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info("DHE-JA06.local.", DEFAULT_PORT),
            )
            second = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info("dhe-ja06.local", DEFAULT_PORT),
            )

        assert first["type"] is FlowResultType.FORM
        assert first["step_id"] == "zeroconf_confirm"
        assert second["type"] is FlowResultType.ABORT
        assert second["reason"] == "already_in_progress"


async def test_options_connection_flow_preserves_token_for_changed_target() -> None:
    """Retarget options without forcing a fresh DHE pairing."""
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
        old_token_path = Path(
            hass.config.path(config_flow.token_file_for_target("old-dhe.local", DEFAULT_PORT))
        )
        new_token_path = Path(
            hass.config.path(config_flow.token_file_for_target("new-dhe.local", DEFAULT_PORT))
        )
        old_token_path.parent.mkdir(parents=True, exist_ok=True)
        old_token_path.write_text("existing-token", encoding="utf-8")

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(return_value=config_flow.SetupPairingResult())
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
            can_connect.assert_awaited_once_with(
                hass,
                "new-dhe.local",
                DEFAULT_PORT,
            )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"] == {
            CONF_HOST: "new-dhe.local",
            CONF_PORT: DEFAULT_PORT,
            CONF_NAME: "New Fixture DHE",
            config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55",
        }
        assert new_token_path.read_text(encoding="utf-8") == "existing-token"
        validate_pairing.assert_not_awaited()


async def test_reconfigure_flow_updates_connection_without_new_entry_with_real_hass_fixture() -> None:
    """Run HA reconfigure flow and verify it updates options on the same entry."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="reconfigure-old.local",
            port=DEFAULT_PORT,
            name="Reconfigure Old DHE",
            unique_id="reconfigure-fixture-dhe",
        )
        entry.add_to_hass(hass)
        old_token_path = Path(
            hass.config.path(
                config_flow.token_file_for_target("reconfigure-old.local", DEFAULT_PORT)
            )
        )
        new_token_path = Path(
            hass.config.path(
                config_flow.token_file_for_target("reconfigure-new.local", DEFAULT_PORT)
            )
        )
        old_token_path.parent.mkdir(parents=True, exist_ok=True)
        old_token_path.write_text("existing-reconfigure-token", encoding="utf-8")

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(return_value=config_flow.SetupPairingResult())
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_RECONFIGURE,
                    "entry_id": entry.entry_id,
                },
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "reconfigure"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={
                    CONF_HOST: "reconfigure-new.local",
                    CONF_PORT: DEFAULT_PORT,
                    CONF_NAME: "Reconfigure New DHE",
                    config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55",
                },
            )
            can_connect.assert_awaited_once_with(
                hass,
                "reconfigure-new.local",
                DEFAULT_PORT,
            )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert entry.unique_id == "reconfigure-fixture-dhe"
        assert entry.options[CONF_HOST] == "reconfigure-new.local"
        assert entry.options[CONF_PORT] == DEFAULT_PORT
        assert entry.options[CONF_NAME] == "Reconfigure New DHE"
        assert entry.options[config_flow.CONF_INTERNAL_SCALD_PROTECTION] == "55"
        assert new_token_path.read_text(encoding="utf-8") == "existing-reconfigure-token"
        validate_pairing.assert_not_awaited()


async def test_reconfigure_flow_reloads_existing_loaded_entry() -> None:
    """Reconfigure should reload the existing loaded entry, not create a new one."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Reconfigure Reload Fixture DHE",
            unique_id="reconfigure-reload-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        reload_entry = AsyncMock(return_value=True)
        with patch.object(hass.config_entries, "async_reload", reload_entry):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_RECONFIGURE,
                    "entry_id": entry.entry_id,
                },
            )
            assert result["type"] is FlowResultType.FORM

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={
                    CONF_HOST: client.host,
                    CONF_PORT: client.port,
                    CONF_NAME: "Reconfigure Reload Updated DHE",
                    config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55",
                },
            )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert reload_entry.await_count >= 1
        assert all(
            call.args == (entry.entry_id,)
            for call in reload_entry.await_args_list
        )
        assert len(hass.config_entries.async_entries(DOMAIN)) == 1
        assert entry.unique_id == "reconfigure-reload-fixture-dhe"

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_reconfigure_flow_updates_name_only_without_connectivity_check() -> None:
    """Changing only the display name must not trigger host/port checks."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="reconfigure-name-only.local",
            port=DEFAULT_PORT,
            name="Reconfigure Name Only DHE",
            unique_id="reconfigure-name-only-fixture-dhe",
        )
        entry.add_to_hass(hass)

        can_connect = AsyncMock(return_value=False)
        with patch.object(config_flow, "_can_connect", can_connect):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_RECONFIGURE,
                    "entry_id": entry.entry_id,
                },
            )
            assert result["type"] is FlowResultType.FORM

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={
                    CONF_HOST: "reconfigure-name-only.local",
                    CONF_PORT: DEFAULT_PORT,
                    CONF_NAME: "Reconfigure Name Updated DHE",
                    config_flow.CONF_INTERNAL_SCALD_PROTECTION: "50",
                },
            )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert entry.options[CONF_NAME] == "Reconfigure Name Updated DHE"
        can_connect.assert_not_awaited()


async def test_reconfigure_flow_updates_tmax_only_without_connectivity_check() -> None:
    """Changing only Tmax must not trigger host/port checks."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="reconfigure-tmax-only.local",
            port=DEFAULT_PORT,
            name="Reconfigure Tmax Only DHE",
            unique_id="reconfigure-tmax-only-fixture-dhe",
        )
        entry.add_to_hass(hass)

        can_connect = AsyncMock(return_value=False)
        with patch.object(config_flow, "_can_connect", can_connect):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_RECONFIGURE,
                    "entry_id": entry.entry_id,
                },
            )
            assert result["type"] is FlowResultType.FORM

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={
                    CONF_HOST: "reconfigure-tmax-only.local",
                    CONF_PORT: DEFAULT_PORT,
                    CONF_NAME: "Reconfigure Tmax Only DHE",
                    config_flow.CONF_INTERNAL_SCALD_PROTECTION: "60",
                },
            )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert entry.options[config_flow.CONF_INTERNAL_SCALD_PROTECTION] == "60"
        can_connect.assert_not_awaited()


async def test_reconfigure_flow_skips_pairing_for_unchanged_target_with_real_hass_fixture() -> None:
    """Keep reconfigure lightweight when host and port are unchanged."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="reconfigure-same.local",
            port=DEFAULT_PORT,
            name="Reconfigure Same DHE",
            unique_id="reconfigure-same-fixture-dhe",
        )
        entry.add_to_hass(hass)

        can_connect = AsyncMock(return_value=False)
        validate_pairing = AsyncMock(return_value=config_flow.SetupPairingResult())
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_RECONFIGURE,
                    "entry_id": entry.entry_id,
                },
            )
            assert result["type"] is FlowResultType.FORM

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={
                    CONF_HOST: "reconfigure-same.local",
                    CONF_PORT: DEFAULT_PORT,
                    CONF_NAME: "Renamed Same DHE",
                    config_flow.CONF_INTERNAL_SCALD_PROTECTION: "60",
                },
            )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert entry.options[CONF_NAME] == "Renamed Same DHE"
        assert entry.options[config_flow.CONF_INTERNAL_SCALD_PROTECTION] == "60"
        can_connect.assert_not_awaited()
        validate_pairing.assert_not_awaited()


async def test_reconfigure_flow_keeps_entered_values_when_new_target_is_unreachable() -> None:
    """Show reconfigure errors against the newly entered target, not old data."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="reconfigure-current.local",
            port=DEFAULT_PORT,
            name="Reconfigure Current DHE",
            unique_id="reconfigure-current-fixture-dhe",
        )
        entry.add_to_hass(hass)

        can_connect = AsyncMock(return_value=False)
        validate_pairing = AsyncMock(return_value=config_flow.SetupPairingResult())
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_RECONFIGURE,
                    "entry_id": entry.entry_id,
                },
            )
            assert result["type"] is FlowResultType.FORM

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={
                    CONF_HOST: "reconfigure-unreachable.local",
                    CONF_PORT: DEFAULT_PORT + 1,
                    CONF_NAME: "Unreachable Reconfigure DHE",
                    config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55",
                },
            )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reconfigure"
        assert result["errors"]["base"] == "cannot_connect"
        defaults = _schema_defaults(result["data_schema"])
        assert defaults[CONF_HOST] == "reconfigure-unreachable.local"
        assert defaults[CONF_PORT] == DEFAULT_PORT + 1
        assert defaults[CONF_NAME] == "Unreachable Reconfigure DHE"
        can_connect.assert_awaited_once_with(
            hass,
            "reconfigure-unreachable.local",
            DEFAULT_PORT + 1,
        )
        validate_pairing.assert_not_awaited()
        assert entry.options == {}


async def test_reconfigure_flow_changes_target_without_existing_token() -> None:
    """Allow target changes even when there is no local token file to preserve."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="reconfigure-retry-old.local",
            port=DEFAULT_PORT,
            name="Reconfigure Retry Old DHE",
            unique_id="reconfigure-retry-fixture-dhe",
        )
        entry.add_to_hass(hass)

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(return_value=config_flow.SetupPairingResult())
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_RECONFIGURE,
                    "entry_id": entry.entry_id,
                },
            )
            assert result["type"] is FlowResultType.FORM

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={
                    CONF_HOST: "reconfigure-retry-new.local",
                    CONF_PORT: DEFAULT_PORT,
                    CONF_NAME: "Reconfigure Retry New DHE",
                    config_flow.CONF_INTERNAL_SCALD_PROTECTION: "50",
                },
            )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert entry.options[CONF_HOST] == "reconfigure-retry-new.local"
        assert entry.options[CONF_NAME] == "Reconfigure Retry New DHE"
        can_connect.assert_awaited_once_with(
            hass,
            "reconfigure-retry-new.local",
            DEFAULT_PORT,
        )
        validate_pairing.assert_not_awaited()


async def test_reconfigure_flow_rejects_target_used_by_another_entry() -> None:
    """Prevent reconfigure from moving one DHE entry onto another target."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        existing = _build_mock_entry(
            host="already-used-dhe.local",
            port=DEFAULT_PORT,
            name="Already Used DHE",
            unique_id="already-used-fixture-dhe",
        )
        existing.add_to_hass(hass)
        entry = _build_mock_entry(
            host="reconfigure-duplicate-old.local",
            port=DEFAULT_PORT,
            name="Reconfigure Duplicate Old DHE",
            unique_id="reconfigure-duplicate-fixture-dhe",
        )
        entry.add_to_hass(hass)

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(return_value=config_flow.SetupPairingResult())
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_RECONFIGURE,
                    "entry_id": entry.entry_id,
                },
            )
            assert result["type"] is FlowResultType.FORM

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={
                    CONF_HOST: "already-used-dhe.local",
                    CONF_PORT: DEFAULT_PORT,
                    CONF_NAME: "Duplicate Target DHE",
                    config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55",
                },
            )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reconfigure"
        assert result["errors"]["base"] == "already_configured"
        defaults = _schema_defaults(result["data_schema"])
        assert defaults[CONF_HOST] == "reconfigure-duplicate-old.local"
        can_connect.assert_not_awaited()
        validate_pairing.assert_not_awaited()
        assert entry.options == {}


async def test_repair_pairing_button_calls_client_when_enabled_with_real_hass_fixture() -> None:
    """Enable the disabled-by-default repair button and press it through HA."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        client.available = False
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

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
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
        assert state.state != "unavailable"

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

        with (
            patch.object(
                integration,
                "DHEClient",
                side_effect=[first_client, second_client],
            ),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
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

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
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


async def test_unavailable_runtime_blocks_controls_except_repair_button() -> None:
    """Do not execute normal DHE controls while runtime availability is false."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    protocol = importlib.import_module(f"custom_components.{DOMAIN}.protocol")
    async with async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        weather_location = {
            "Name": "Berlin",
            "Country": "Germany",
            "LocationId": "ID=1",
        }
        radio_station = {"Id": 1, "Name": "Radio Test", "Country": "Germany"}
        client.last_weather_state = {
            "location": weather_location,
            "favorites": [weather_location],
        }
        client.last_radio_state = {
            "play": False,
            "volume": 40,
            "station": radio_station,
            "favorites": [radio_station],
        }
        client.last_measurements.update(
            {
                protocol.ID_BATH_FILL_TARGET_VOLUME: 80,
                protocol.ID_BRUSH_TIMER_ACTIVATION: True,
                protocol.ID_ECO_MODE: False,
            }
        )
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Unavailable Control Fixture DHE",
            unique_id="unavailable-control-fixture-dhe",
        )
        entry.add_to_hass(hass)

        registry = er.async_get(hass)
        registry.async_get_or_create(
            "button",
            DOMAIN,
            f"{DOMAIN}_{entry.entry_id}_reset_brush_timer",
            suggested_object_id="unavailable_control_fixture_dhe_reset_brush_timer",
            disabled_by=None,
        )

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        entity_ids = {
            "button": _entity_id_for_key(
                hass,
                entry.entry_id,
                "button",
                "reset_brush_timer",
            ),
            "climate": _entity_id_for_key(hass, entry.entry_id, "climate", "setpoint"),
            "media_player": _entity_id_for_key(
                hass,
                entry.entry_id,
                "media_player",
                "radio",
            ),
            "number": _entity_id_for_key(
                hass,
                entry.entry_id,
                "number",
                "bath_fill_target_volume",
            ),
            "switch": _entity_id_for_key(hass, entry.entry_id, "switch", "eco_mode"),
            "wellness": _entity_id_for_key(
                hass,
                entry.entry_id,
                "switch",
                "wellness_winter_refresh",
            ),
        }

        client.emit_availability(False)
        await hass.async_block_till_done()
        assert all(
            (state := hass.states.get(entity_id)) is not None
            and state.state == "unavailable"
            for entity_id in entity_ids.values()
        )

        blocked_calls = (
            ("button", "press", {"entity_id": entity_ids["button"]}),
            (
                "climate",
                "set_temperature",
                {"entity_id": entity_ids["climate"], "temperature": 39},
            ),
            ("media_player", "media_play", {"entity_id": entity_ids["media_player"]}),
            (
                "number",
                "set_value",
                {"entity_id": entity_ids["number"], "value": 90},
            ),
            ("switch", "turn_on", {"entity_id": entity_ids["switch"]}),
            ("switch", "turn_on", {"entity_id": entity_ids["wellness"]}),
        )
        for domain, service, data in blocked_calls:
            try:
                await hass.services.async_call(domain, service, data, blocking=True)
            except HomeAssistantError as err:
                assert "DHE is unavailable" in str(err)

        assert client.reset_brush_timer_calls == 0
        assert client.temperature_calls == []
        assert client.radio_play_calls == []
        assert client.bath_fill_target_volume_calls == []
        assert client.eco_mode_calls == []
        assert client.wellness_program_calls == []

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

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
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

    with (
        patch.object(integration, "DHEClient", return_value=client),
        patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    runtime = entry.runtime_data
    start_task = runtime.start_task
    assert runtime.client is client
    assert client.start_called
    assert start_task is not None
    assert not start_task.done()
    assert hass.services.has_service(DOMAIN, "search_weather_location")
    assert hass.states.get("climate.fixture_dhe_water_heating") is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert client.stop_called
    assert start_task.done()
    assert getattr(entry, "runtime_data", None) is None
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


def _zeroconf_info(
    hostname: str | None,
    port: Any,
    *,
    host: str | None | object = _DEFAULT_ZEROCONF_HOST,
    name: str | None = None,
    ip: str = "192.0.2.124",
) -> types.SimpleNamespace:
    """Build a DHE Zeroconf discovery payload for config-flow tests."""
    service_hostname = hostname or f"{ip}.local."
    host_value = ip if host is _DEFAULT_ZEROCONF_HOST else host
    return types.SimpleNamespace(
        host=host_value,
        ip_address=ip_address(ip),
        ip_addresses=[ip_address(ip)],
        port=port,
        hostname=hostname,
        type="_ste-dhe._tcp.local.",
        name=name or f"{service_hostname.rstrip('.')}._ste-dhe._tcp.local.",
        properties={},
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
