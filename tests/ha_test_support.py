"""Shared real Home Assistant fixtures and DHE runtime test doubles."""

from __future__ import annotations

import asyncio
import datetime as dt
import importlib
import sys
import types
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import bootstrap
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
    MAJOR_VERSION,
    MINOR_VERSION,
)
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
)
from homeassistant.helpers import (
    category_registry as cr,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers import (
    issue_registry as ir,
)
from homeassistant.helpers import (
    label_registry as lr,
)
from homeassistant.helpers import (
    restore_state as rs,
)

if importlib.util.find_spec("pytest_homeassistant"):
    from pytest_homeassistant.common import (
        MockConfigEntry,
        StoreWithoutWriteLoad,
    )
    from pytest_homeassistant.common import (
        async_test_home_assistant as _ha_async_test_home_assistant,
    )
else:
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
        StoreWithoutWriteLoad,
    )
    from pytest_homeassistant_custom_component.common import (
        async_test_home_assistant as _ha_async_test_home_assistant,
    )

pytestmark = pytest.mark.asyncio
__all__ = ["PAIRING_TOKEN", "STORED_TOKEN", "FakeDHEEngineIOServer"]
DOMAIN = "stiebel_dhe_connect"
DEFAULT_PORT = 8443
ROOT = Path(__file__).resolve().parents[1]
HA_CONFIG_DIR = ROOT / ".pytest_cache" / f"ha-config-{MAJOR_VERSION}-{MINOR_VERSION}"
_DEFAULT_ZEROCONF_HOST = object()

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from tests.test_fake_dhe_engineio_server import (
        PAIRING_TOKEN,
        STORED_TOKEN,
        FakeDHEEngineIOServer,
    )
except ModuleNotFoundError:
    pass


async def _async_get_test_time_zone(_time_zone: str) -> dt.tzinfo:
    """Avoid aiozoneinfo lookups hanging the HA fixture in sandboxed tests."""
    return dt.UTC


async def _async_load_no_translations(
    _hass: HomeAssistant,
    _integrations: set[str],
) -> dict[str, Any]:
    """Avoid HA translation loading paths that can block the sandboxed fixture."""
    return {}


async def _async_load_test_network_adapters() -> list[dict[str, Any]]:
    """Return deterministic network adapters without opening system sockets."""
    return [
        {
            "name": "lo",
            "index": None,
            "enabled": True,
            "auto": True,
            "default": True,
            "ipv4": [{"address": "127.0.0.1", "network_prefix": 8}],
            "ipv6": [],
        }
    ]


def _get_test_source_ip(*_args: Any, **_kwargs: Any) -> str:
    """Return a deterministic source IP without creating sockets."""
    return "127.0.0.1"


async def _async_load_registry_compat(
    hass: HomeAssistant,
    registry_module: Any,
    registry_cls: type[Any],
) -> None:
    """Load registries across HA versions with explicit async_get setup."""
    try:
        await registry_module.async_load(hass)
        return
    except RuntimeError as err:
        if (
            registry_module.DATA_REGISTRY in hass.data
            or "registry not set up" not in str(err)
        ):
            raise

    registry = registry_cls(hass)
    hass.data[registry_module.DATA_REGISTRY] = registry
    await registry.async_load()


async def _async_load_test_registries(hass: HomeAssistant) -> None:
    """Load the HA registries needed by entity platforms without floor storage."""
    with (
        patch.object(StoreWithoutWriteLoad, "async_load", return_value=None),
        patch(
            "homeassistant.helpers.area_registry.AreaRegistryStore",
            StoreWithoutWriteLoad,
        ),
        patch(
            "homeassistant.helpers.device_registry.DeviceRegistryStore",
            StoreWithoutWriteLoad,
        ),
        patch(
            "homeassistant.helpers.entity_registry.EntityRegistryStore",
            StoreWithoutWriteLoad,
        ),
        patch(
            "homeassistant.helpers.storage.Store",
            StoreWithoutWriteLoad,
        ),
        patch(
            "homeassistant.helpers.issue_registry.IssueRegistryStore",
            StoreWithoutWriteLoad,
        ),
        patch(
            "homeassistant.helpers.restore_state.RestoreStateData.async_setup_dump",
            return_value=None,
        ),
        patch("homeassistant.helpers.restore_state.start.async_at_start"),
    ):
        await _async_load_registry_compat(hass, ar, ar.AreaRegistry)
        await _async_load_registry_compat(hass, cr, cr.CategoryRegistry)
        await _async_load_registry_compat(hass, dr, dr.DeviceRegistry)
        await _async_load_registry_compat(hass, er, er.EntityRegistry)
        await _async_load_registry_compat(hass, ir, ir.IssueRegistry)
        await _async_load_registry_compat(hass, lr, lr.LabelRegistry)
        await rs.async_load(hass)
    hass.data[bootstrap.DATA_REGISTRIES_LOADED] = None


@asynccontextmanager
async def _async_test_home_assistant(
    **kwargs: Any,
) -> AsyncIterator[HomeAssistant]:
    """Return a HA test instance with deterministic timezone setup."""
    kwargs.setdefault("load_registries", False)
    kwargs.setdefault("initial_state", CoreState.not_running)
    config_dir = HA_CONFIG_DIR
    config_dir.mkdir(parents=True, exist_ok=True)
    kwargs.setdefault("config_dir", str(config_dir))
    with (
        patch("homeassistant.util.dt.async_get_time_zone", _async_get_test_time_zone),
        patch(
            "homeassistant.core_config.dt_util.async_get_time_zone",
            _async_get_test_time_zone,
        ),
        patch(
            "homeassistant.helpers.translation.async_load_integrations",
            _async_load_no_translations,
        ),
        patch(
            "homeassistant.components.network.util.async_load_adapters",
            _async_load_test_network_adapters,
        ),
        patch(
            "homeassistant.components.network.network.async_load_adapters",
            _async_load_test_network_adapters,
        ),
        patch(
            "homeassistant.components.network.util.async_get_source_ip",
            _get_test_source_ip,
        ),
    ):
        async with _ha_async_test_home_assistant(**kwargs) as hass:
            try:
                await _async_load_test_registries(hass)
                await hass.async_start()
                yield hass
            finally:
                await hass.async_stop(force=True)


@pytest.fixture(autouse=True)
def _isolate_discovery_cache():
    """Keep persisted discovery prompts from leaking between HA fixture tests."""
    cache_path = (
        HA_CONFIG_DIR
        / ".storage"
        / "stiebel_dhe_connect_discovery_cache"
    )
    cache_path.unlink(missing_ok=True)
    yield
    cache_path.unlink(missing_ok=True)


def _schema_defaults(schema: Any) -> dict[str, Any]:
    """Return probatio marker defaults from a flow schema."""
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
        async_get_network = network_module.async_get_network
    await async_get_network(hass)


class _FixtureDHEClient:
    """Minimal DHE client test double for real Home Assistant runtime setup."""

    host = "127.0.0.1"
    port = DEFAULT_PORT
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
        self.bridge_temperature_maximum_calls = 0
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
        await self._stopped.wait()

    async def stop(self) -> None:
        """Stop the fake background session."""
        self.stop_called = True
        self._stopped.set()

    async def request_measurement_refresh(self, **_kwargs: Any) -> None:
        """Mock a measurement refresh request from the sensor runtime path."""
        return

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

    async def bridge_temperature_maximum(self) -> bool:
        """Record a temporary max-override button call."""
        self.bridge_temperature_maximum_calls += 1
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
    def add_measurement_callback(
        self,
        callback_fn: Callable[[int, Any], None],
        *,
        replay: bool = True,
    ):
        self.callbacks["measurement"].append(callback_fn)
        if replay:
            for odb_id, value in self.last_measurements.items():
                callback_fn(odb_id, value)
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
    assert all(not callbacks for callbacks in client.callbacks.values())


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
    properties: dict[str, Any] | None = None,
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
        properties=properties or {},
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
