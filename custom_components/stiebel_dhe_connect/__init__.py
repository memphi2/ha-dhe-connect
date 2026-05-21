"""DHE Connect custom integration."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass
from typing import Any, cast

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, SOURCE_REAUTH
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from .action_error_helpers import raise_if_dhe_unavailable, run_dhe_action
from .async_helpers import (
    cancel_task_if_pending,
    create_background_task,
    task_cancel_callback,
)
from .client import DHEClient
from .config_entry_helpers import merged_entry_data, entry_target
from .connection_helpers import normalize_host, validate_port
from .connection_probe import async_can_connect as _async_can_connect
from .const import (
    DEFAULT_NAME,
    DEFAULT_PORT,
    DOMAIN,
    PLATFORMS,
)
from .repair_issues import (
    DISCOVERY_CONFLICT_ISSUE,
    DEVICE_UNREACHABLE_ISSUE,
    HOST_CHANGED_OR_UNREACHABLE_ISSUE,
    PAIRING_REQUIRED_ISSUE,
    TOKEN_INVALID_ISSUE,
    async_create_repair_issue,
    async_delete_repair_issues,
)
from .runtime_helpers import (
    clear_runtime_data,
    iter_loaded_runtime_data,
    set_runtime_data,
)
from .service_helpers import WEATHER_RESULT_NUMBER_MAX
from .token_file_helpers import (
    LEGACY_TOKEN_FILE,
    legacy_token_file_for_entry,
    token_file_for_target,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_SEARCH_WEATHER_LOCATION = "search_weather_location"
SERVICE_ADD_WEATHER_FAVORITE = "add_weather_favorite"
SERVICE_TOGGLE_WEATHER_FAVORITE = "toggle_weather_favorite"
SERVICE_REMOVE_WEATHER_FAVORITE = "remove_weather_favorite"
SERVICE_SELECT_WEATHER_LOCATION = "select_weather_location"

ATTR_COUNTRY_ID = "country_id"
ATTR_ENTRY_ID = "entry_id"
ATTR_LOCATION_ID = "location_id"
ATTR_NAME = "name"
ATTR_RESULT_NUMBER = "result_number"
WEATHER_SEARCH_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_NAME): cv.string,
        vol.Required(ATTR_COUNTRY_ID): vol.Coerce(int),
        vol.Optional(ATTR_ENTRY_ID): cv.string,
    }
)
WEATHER_LOCATION_ACTION_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_NAME): cv.string,
        vol.Optional(ATTR_COUNTRY_ID): vol.Coerce(int),
        vol.Optional(ATTR_LOCATION_ID): cv.string,
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Optional(ATTR_RESULT_NUMBER, default=1): vol.All(
            vol.Coerce(int),
            vol.Range(min=1, max=WEATHER_RESULT_NUMBER_MAX),
        ),
    }
)
WEATHER_TOGGLE_FAVORITE_SCHEMA = WEATHER_LOCATION_ACTION_SCHEMA
WEATHER_SELECT_LOCATION_SCHEMA = WEATHER_LOCATION_ACTION_SCHEMA
WEATHER_ADD_FAVORITE_SCHEMA = WEATHER_LOCATION_ACTION_SCHEMA
WEATHER_REMOVE_FAVORITE_SCHEMA = WEATHER_LOCATION_ACTION_SCHEMA
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
STALE_SENSOR_STATISTIC_TRANSLATION_KEYS = frozenset(
    {
        "odb_possible_energy_saving",
        "odb_actual_water_saving",
    }
)


@dataclass
class DHEConnectRuntimeData:
    """Runtime data for the integration."""

    client: DHEClient
    name: str
    start_task: asyncio.Task[Any] | None = None


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up integration-wide services."""
    del config
    _async_register_services(hass)
    return True


def _token_file_for_entry(entry: ConfigEntry) -> str:
    target = entry_target(entry)
    if target is None:
        return legacy_token_file_for_entry(entry.entry_id)
    host, port = target
    return token_file_for_target(host, port)


async def _async_migrate_legacy_token_if_needed(
    hass: HomeAssistant,
    entry: ConfigEntry,
    token_file: str,
) -> None:
    """Move legacy single-entry token file when upgrading old installs."""
    target_path = (
        token_file if os.path.isabs(token_file) else hass.config.path(token_file)
    )
    legacy_path = hass.config.path(LEGACY_TOKEN_FILE)
    if len(hass.config_entries.async_entries(DOMAIN)) != 1:
        return

    def _move() -> bool:
        if os.path.exists(target_path) or not os.path.exists(legacy_path):
            return False
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        shutil.move(legacy_path, target_path)
        return True

    migrated = await hass.async_add_executor_job(_move)
    if not migrated:
        return
    _LOGGER.debug(
        "Migrated legacy token file for entry_id=%s to %s (legacy file consumed)",
        entry.entry_id,
        token_file,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up DHE Connect from a config entry."""
    data = merged_entry_data(entry)
    target = entry_target(entry)
    if target is None:
        raise HomeAssistantError("Invalid DHE host/port in config entry")
    reachable_target = await _async_first_reachable_entry_target(hass, entry, target)
    if reachable_target is None:
        name = str(data.get(CONF_NAME, entry.title or DEFAULT_NAME)).strip() or DEFAULT_NAME
        host, port = target
        async_create_repair_issue(
            hass,
            entry.entry_id,
            _setup_unreachable_issue_type(entry, target),
            name,
            placeholders={CONF_HOST: host, CONF_PORT: port},
        )
        raise ConfigEntryNotReady("Could not connect to DHE before setup")
    host, port = reachable_target
    name = data.get(CONF_NAME, DEFAULT_NAME)

    token_file = _token_file_for_entry(entry)
    await _async_migrate_legacy_token_if_needed(hass, entry, token_file)

    client = DHEClient(
        hass=hass,
        host=host,
        port=port,
        token_file=token_file,
        name="Home Assistant",
    )
    client.device_identifier = _device_identifier_for_entry(entry)
    client.legacy_device_identifier = _legacy_device_identifier_for_entry(
        hass,
        entry,
        host,
    )
    client.legacy_device_identifiers = _legacy_device_identifiers_for_entry(
        hass,
        entry,
        host,
        port,
        client.device_identifier,
    )

    runtime = DHEConnectRuntimeData(
        client=client,
        name=name,
    )
    set_runtime_data(entry, runtime)

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except asyncio.CancelledError:
        raise
    except Exception as err:
        _LOGGER.exception(
            "Failed to initialize DHE platforms for entry=%s: %s",
            entry.entry_id,
            err,
        )
        clear_runtime_data(entry)
        raise
    _async_cleanup_empty_legacy_devices(hass, entry, client.device_identifier)
    _async_clear_stale_sensor_statistic_issues(hass, entry)
    _async_register_services(hass)
    _async_register_reauth_trigger(hass, entry, client)
    runtime.start_task = _start_client_background(hass, entry, client)
    entry.async_on_unload(task_cancel_callback(runtime.start_task))
    async_delete_repair_issues(hass, entry.entry_id)
    _async_clear_config_entry_reauth(hass, entry)
    _async_schedule_config_entry_reauth_clear(hass, entry)
    _async_schedule_connected_issue_cleanup(hass, entry, client)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_first_reachable_entry_target(
    hass: HomeAssistant,
    entry: ConfigEntry,
    primary_target: tuple[str, int],
) -> tuple[str, int] | None:
    """Return the first reachable target, allowing Zeroconf hostname fallbacks."""
    for host, port in _entry_setup_target_candidates(entry, primary_target):
        if await _async_can_connect(hass, host, port):
            return host, port
    return None


def _entry_setup_target_candidates(
    entry: ConfigEntry,
    primary_target: tuple[str, int],
) -> tuple[tuple[str, int], ...]:
    """Return setup targets in preference order without changing entry data."""
    candidates = [primary_target]
    data_target = _target_from_entry_data(entry)
    if data_target is not None and data_target not in candidates:
        candidates.append(data_target)
    return tuple(candidates)


def _target_from_entry_data(entry: ConfigEntry) -> tuple[str, int] | None:
    """Return the original config-entry data target, ignoring option overrides."""
    try:
        return (
            normalize_host(str(entry.data[CONF_HOST])),
            validate_port(entry.data.get(CONF_PORT, DEFAULT_PORT)),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _setup_unreachable_issue_type(
    entry: ConfigEntry,
    merged_target: tuple[str, int],
) -> str:
    """Classify setup-time unreachable targets."""
    data_target = _target_from_entry_data(entry)
    if data_target is not None and data_target != merged_target:
        return HOST_CHANGED_OR_UNREACHABLE_ISSUE
    return DEVICE_UNREACHABLE_ISSUE


def _device_identifier_for_entry(entry: ConfigEntry) -> str:
    """Return the stable HA device identifier for one config entry."""
    if entry.unique_id:
        return f"device:{entry.unique_id}"
    return f"entry:{entry.entry_id}"


def _legacy_device_identifiers_for_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    host: str,
    port: int,
    stable_identifier: str,
) -> set[str]:
    """Return old host-derived identifiers that should merge into the device."""
    identifiers = {f"{host}:{port}"}
    device_registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        for domain, identifier in device.identifiers:
            if domain == DOMAIN and identifier != stable_identifier:
                identifiers.add(identifier)
    return identifiers


def _legacy_device_identifier_for_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    host: str,
) -> str | None:
    """Return legacy host identifier only for upgraded installs.

    We keep `(DOMAIN, host)` only when this config entry already has a device
    with that old identifier in the registry. New installs keep only the
    host:port identifier to avoid cross-port device merges.
    """
    device_registry = dr.async_get(hass)
    legacy_identifier = (DOMAIN, host)
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if legacy_identifier in device.identifiers:
            return host
    return None


def _async_cleanup_empty_legacy_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
    stable_identifier: str | None,
) -> None:
    """Remove empty host-derived devices left behind by older identity schemes."""
    if not stable_identifier:
        return

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    canonical_identifier = (DOMAIN, stable_identifier)
    dhe_devices = [
        device
        for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id)
        if any(domain == DOMAIN for domain, _identifier in device.identifiers)
    ]
    if not dhe_devices:
        return

    identifiers = {canonical_identifier}
    for device in dhe_devices:
        identifiers.update(
            (domain, identifier)
            for domain, identifier in device.identifiers
            if domain == DOMAIN
        )

    entity_counts = {
        device.id: len(
            er.async_entries_for_device(
                entity_registry,
                device.id,
                include_disabled_entities=True,
            )
        )
        for device in dhe_devices
    }
    canonical_device = next(
        (device for device in dhe_devices if canonical_identifier in device.identifiers),
        None,
    )
    target_device = canonical_device
    if canonical_device is None:
        target_device = max(
            dhe_devices,
            key=lambda device: entity_counts[device.id],
        )
    elif entity_counts[canonical_device.id] == 0:
        entity_devices = [
            device for device in dhe_devices if entity_counts[device.id] > 0
        ]
        if entity_devices:
            target_device = max(
                entity_devices,
                key=lambda device: entity_counts[device.id],
            )

    if target_device is None:
        return

    if not identifiers.issubset(target_device.identifiers):
        device_registry.async_update_device(
            target_device.id,
            merge_identifiers=identifiers,
        )

    canonical_device_id = target_device.id
    for device in dhe_devices:
        if device.id == canonical_device_id:
            continue
        for entity_entry in er.async_entries_for_device(
            entity_registry,
            device.id,
            include_disabled_entities=True,
        ):
            entity_registry.async_update_entity(
                entity_entry.entity_id,
                device_id=canonical_device_id,
            )
        device_registry.async_remove_device(device.id)


@callback
def _async_clear_stale_sensor_statistic_issues(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Clear HA statistic issues caused by older invalid saving sensor classes."""
    entity_registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if entity.platform != DOMAIN:
            continue
        if entity.translation_key not in STALE_SENSOR_STATISTIC_TRANSLATION_KEYS:
            continue
        ir.async_delete_issue(
            hass,
            "sensor",
            f"mean_type_changed_{entity.entity_id}",
        )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    runtime = getattr(entry, "runtime_data", None)
    unloaded_result = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    unloaded = bool(unloaded_result)

    if unloaded:
        if runtime is not None:
            if runtime.start_task is not None:
                await cancel_task_if_pending(runtime.start_task)
            await runtime.client.stop()
        clear_runtime_data(entry)
        if not any(iter_loaded_runtime_data(hass)):
            _async_unregister_services(hass)

    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _start_client_background(
    hass: HomeAssistant,
    entry: ConfigEntry,
    client: DHEClient,
) -> asyncio.Task[Any]:
    """Start the persistent DHE session without blocking entity setup."""
    create_task = getattr(entry, "async_create_background_task", None)
    if create_task is not None:
        return cast(
            asyncio.Task[Any],
            create_task(hass, client.start(), "stiebel_dhe_connect_start"),
        )
    return create_background_task(hass, client.start(), "stiebel_dhe_connect_start")


def _async_register_reauth_trigger(
    hass: HomeAssistant,
    entry: ConfigEntry,
    client: DHEClient,
) -> None:
    """Create at most one active DHE repair issue from runtime diagnostics."""
    active_issue_type: str | None = None
    entry_name = str(
        merged_entry_data(entry).get(CONF_NAME, entry.title or DEFAULT_NAME)
    ).strip() or DEFAULT_NAME

    @callback
    def _target_placeholders() -> dict[str, str]:
        target = entry_target(entry)
        if target is None:
            return {}
        host, port = target
        return {CONF_HOST: host, CONF_PORT: str(port)}

    @callback
    def _create_issue(issue_type: str) -> None:
        nonlocal active_issue_type
        if active_issue_type == issue_type:
            return
        async_delete_repair_issues(hass, entry.entry_id, keep_types=(issue_type,))
        async_create_repair_issue(
            hass,
            entry.entry_id,
            issue_type,
            entry_name,
            placeholders=_target_placeholders(),
        )
        active_issue_type = issue_type

    @callback
    def _handle_diagnostic_update(state: dict[str, Any]) -> None:
        nonlocal active_issue_type
        if state.get("connection_state") == "connected":
            active_issue_type = None
            async_delete_repair_issues(hass, entry.entry_id)
            _async_clear_config_entry_reauth(hass, entry)
            _async_clear_stale_sensor_statistic_issues(hass, entry)
            _async_schedule_connected_issue_cleanup(hass, entry, client)
            return

        if (
            state.get("auth_failure") is True
            or state.get("connection_state") == "auth_failed"
        ):
            issue_type = _auth_repair_issue_type(state)
            _create_issue(issue_type)
            _async_clear_config_entry_reauth(hass, entry)
            _async_schedule_config_entry_reauth_clear(hass, entry)
            return

        runtime_issue_type = _runtime_connectivity_issue_type(entry, client, state)
        if runtime_issue_type is not None:
            _create_issue(runtime_issue_type)
            return

        if active_issue_type in {
            DEVICE_UNREACHABLE_ISSUE,
            DISCOVERY_CONFLICT_ISSUE,
            HOST_CHANGED_OR_UNREACHABLE_ISSUE,
        }:
            active_issue_type = None
            async_delete_repair_issues(hass, entry.entry_id)

    entry.async_on_unload(client.add_diagnostic_callback(_handle_diagnostic_update))


def _auth_repair_issue_type(state: dict[str, Any]) -> str:
    """Classify auth failures into pairing-required vs token-invalid."""
    reason = str(state.get("last_reconnect_reason", "")).lower()
    if any(
        marker in reason
        for marker in (
            "auth",
            "token",
            "unauthorized",
            "invalid",
            "forbidden",
        )
    ):
        return TOKEN_INVALID_ISSUE
    return PAIRING_REQUIRED_ISSUE


def _runtime_connectivity_issue_type(
    entry: ConfigEntry,
    client: DHEClient,
    state: dict[str, Any],
) -> str | None:
    """Return connectivity-related repair type or None."""
    connection_state = str(state.get("connection_state", ""))
    if (
        state.get("discovery_conflict") is True
        or connection_state == DISCOVERY_CONFLICT_ISSUE
    ):
        return DISCOVERY_CONFLICT_ISSUE
    if connection_state not in {"reconnecting", "unavailable"}:
        return None
    reconnect_state = getattr(client, "reconnect_supervisor_state", None)
    if callable(reconnect_state):
        reconnect_state = reconnect_state()
    if not isinstance(reconnect_state, dict):
        reconnect_state = {}
    if (
        not reconnect_state
        and state.get("should_mark_unavailable") is True
    ):
        reconnect_state = {"should_mark_unavailable": True}
    if reconnect_state.get("should_mark_unavailable") is not True:
        return None

    merged_target = entry_target(entry)
    data_target = _target_from_entry_data(entry)
    if (
        merged_target is not None
        and data_target is not None
        and merged_target != data_target
    ):
        return HOST_CHANGED_OR_UNREACHABLE_ISSUE

    reason = str(state.get("last_reconnect_reason", "")).lower()
    if _reason_indicates_runtime_auth_issue(reason):
        return TOKEN_INVALID_ISSUE
    if _reason_indicates_host_target_issue(reason):
        return HOST_CHANGED_OR_UNREACHABLE_ISSUE
    return DEVICE_UNREACHABLE_ISSUE


def _reason_indicates_runtime_auth_issue(reason: str) -> bool:
    """Return True when reconnect diagnostics indicate auth/token loss."""
    return any(
        marker in reason
        for marker in (
            "unauthorized",
            "forbidden",
            "auth",
            "token",
            "session id unknown",
            "invalid session",
        )
    )


def _reason_indicates_host_target_issue(reason: str) -> bool:
    """Return True when reconnect diagnostics point to host/target problems."""
    return any(
        marker in reason
        for marker in (
            "name or service not known",
            "temporary failure in name resolution",
            "nxdomain",
            "dns",
            "host lookup",
            "no route to host",
            "network is unreachable",
        )
    )


@callback
def _async_clear_config_entry_reauth(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Abort stale HA reauth flows and delete HA's generic stale reauth issue."""
    for flow in _async_entry_reauth_flows(hass, entry):
        if flow_id := flow.get("flow_id"):
            hass.config_entries.flow.async_abort(flow_id)
    ir.async_delete_issue(
        hass,
        "homeassistant",
        f"config_entry_reauth_{entry.domain}_{entry.entry_id}",
    )


def _async_entry_reauth_flows(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> tuple[ConfigFlowResult, ...]:
    """Return active reauth flows that belong to a config entry."""
    flows: list[ConfigFlowResult] = []
    for flow in hass.config_entries.flow.async_progress_by_handler(entry.domain):
        context = flow.get("context") or {}
        if context.get("source") != SOURCE_REAUTH:
            continue
        if context.get("entry_id") == entry.entry_id:
            flows.append(flow)
            continue
        if entry.unique_id and context.get("unique_id") == entry.unique_id:
            flows.append(flow)
    return tuple(flows)


def _async_schedule_config_entry_reauth_clear(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Schedule a delayed cleanup for generic HA reauth leftovers."""
    task = create_background_task(
        hass,
        _async_clear_config_entry_reauth_delayed(hass, entry),
        name="stiebel_dhe_connect_clear_stale_reauth",
    )
    entry.async_on_unload(task_cancel_callback(task))


async def _async_clear_config_entry_reauth_delayed(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Clear generic HA reauth issue after HA has settled issue creation."""
    await asyncio.sleep(0)
    _async_clear_config_entry_reauth(hass, entry)
    await asyncio.sleep(1)
    _async_clear_config_entry_reauth(hass, entry)


def _async_schedule_connected_issue_cleanup(
    hass: HomeAssistant,
    entry: ConfigEntry,
    client: DHEClient,
) -> None:
    """Schedule stale Repairs cleanup once the runtime is truly connected."""
    task = create_background_task(
        hass,
        _async_clear_issues_when_connected(hass, entry, client),
        name="stiebel_dhe_connect_clear_connected_issues",
    )
    entry.async_on_unload(task_cancel_callback(task))


async def _async_clear_issues_when_connected(
    hass: HomeAssistant,
    entry: ConfigEntry,
    client: DHEClient,
) -> None:
    """Clear stale repair issues after connected state reaches HA."""
    for _attempt in range(30):
        if client.diagnostic_state.get("connection_state") == "connected":
            break
        await asyncio.sleep(1)
    else:
        return

    for delay in (0, 1, 5):
        if delay:
            await asyncio.sleep(delay)
        if client.diagnostic_state.get("connection_state") != "connected":
            return
        async_delete_repair_issues(hass, entry.entry_id)
        _async_clear_config_entry_reauth(hass, entry)
        _async_clear_stale_sensor_statistic_issues(hass, entry)


def _async_register_services(hass: HomeAssistant) -> None:
    """Register integration services once."""

    async def _resolve_weather_location_for_service(
        call: ServiceCall,
        *,
        unavailable_message: str,
        missing_country_error: str,
    ) -> tuple[DHEClient, dict[str, Any] | str]:
        """Resolve one weather location payload from a service call."""
        runtime = _resolve_runtime(hass, call.data.get(ATTR_ENTRY_ID))
        client = runtime.client
        raise_if_dhe_unavailable(
            client,
            unavailable_message,
        )
        data = call.data
        results = await _weather_results_from_service_input(
            client,
            data,
            missing_country_error=missing_country_error,
        )
        location = _select_weather_location(
            client.last_weather_state,
            results,
            data.get(ATTR_LOCATION_ID),
            data[ATTR_RESULT_NUMBER],
            allow_raw_location_id=True,
        )
        return client, location

    async def async_search_weather_location(call: ServiceCall) -> None:
        runtime = _resolve_runtime(hass, call.data.get(ATTR_ENTRY_ID))
        raise_if_dhe_unavailable(
            runtime.client,
            "DHE is unavailable; cannot search weather locations",
        )
        await _run_dhe_service_action(
            runtime.client.search_weather_locations(
                call.data[ATTR_NAME],
                call.data[ATTR_COUNTRY_ID],
            ),
            "Could not search DHE weather locations",
        )

    async def async_toggle_weather_favorite(call: ServiceCall) -> None:
        client, location = await _resolve_weather_location_for_service(
            call,
            unavailable_message="DHE is unavailable; cannot toggle weather favorite",
            missing_country_error=(
                "country_id is required when toggling a weather favorite by name"
            ),
        )
        await _run_dhe_service_action(
            client.toggle_weather_favorite(_weather_location_payload(location)),
            "Could not toggle DHE weather favorite",
        )

    async def async_add_weather_favorite(call: ServiceCall) -> None:
        client, location = await _resolve_weather_location_for_service(
            call,
            unavailable_message="DHE is unavailable; cannot add weather favorite",
            missing_country_error=(
                "country_id is required when adding a weather favorite by name"
            ),
        )
        await _run_dhe_service_action(
            client.add_weather_favorite(_weather_location_payload(location)),
            "Could not add DHE weather favorite",
        )

    async def async_remove_weather_favorite(call: ServiceCall) -> None:
        client, location = await _resolve_weather_location_for_service(
            call,
            unavailable_message="DHE is unavailable; cannot remove weather favorite",
            missing_country_error=(
                "country_id is required when removing a weather favorite by name"
            ),
        )
        await _run_dhe_service_action(
            client.remove_weather_favorite(_weather_location_payload(location)),
            "Could not remove DHE weather favorite",
        )

    async def async_select_weather_location(call: ServiceCall) -> None:
        client, location = await _resolve_weather_location_for_service(
            call,
            unavailable_message="DHE is unavailable; cannot select weather location",
            missing_country_error=(
                "country_id is required when selecting a weather location by name"
            ),
        )
        await _run_dhe_service_action(
            client.select_weather_location(location),
            "Could not select DHE weather location",
        )

    service_registrations = (
        (
            SERVICE_SEARCH_WEATHER_LOCATION,
            async_search_weather_location,
            WEATHER_SEARCH_SCHEMA,
        ),
        (
            SERVICE_ADD_WEATHER_FAVORITE,
            async_add_weather_favorite,
            WEATHER_ADD_FAVORITE_SCHEMA,
        ),
        (
            SERVICE_TOGGLE_WEATHER_FAVORITE,
            async_toggle_weather_favorite,
            WEATHER_TOGGLE_FAVORITE_SCHEMA,
        ),
        (
            SERVICE_REMOVE_WEATHER_FAVORITE,
            async_remove_weather_favorite,
            WEATHER_REMOVE_FAVORITE_SCHEMA,
        ),
        (
            SERVICE_SELECT_WEATHER_LOCATION,
            async_select_weather_location,
            WEATHER_SELECT_LOCATION_SCHEMA,
        ),
    )
    for service_name, service_handler, service_schema in service_registrations:
        if hass.services.has_service(DOMAIN, service_name):
            continue
        hass.services.async_register(
            DOMAIN,
            service_name,
            service_handler,
            schema=service_schema,
        )


def _async_unregister_services(hass: HomeAssistant) -> None:
    """Remove integration services when the last entry unloads."""
    for service in (
        SERVICE_SEARCH_WEATHER_LOCATION,
        SERVICE_ADD_WEATHER_FAVORITE,
        SERVICE_TOGGLE_WEATHER_FAVORITE,
        SERVICE_REMOVE_WEATHER_FAVORITE,
        SERVICE_SELECT_WEATHER_LOCATION,
    ):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)


async def _run_dhe_service_action(
    action: Any,
    failure_message: str,
) -> Any:
    """Run one DHE-backed HA service action and expose DHE failures to HA."""
    return await run_dhe_action(action, failure_message)


def _resolve_runtime(
    hass: HomeAssistant,
    entry_id: str | None = None,
) -> DHEConnectRuntimeData:
    """Resolve runtime by entry_id or infer it when only one entry exists."""
    runtimes = dict(iter_loaded_runtime_data(hass))
    if not runtimes:
        raise HomeAssistantError("DHE Connect is not loaded")
    if entry_id:
        runtime = runtimes.get(entry_id)
        if runtime is None:
            raise HomeAssistantError(f"DHE Connect entry_id not loaded: {entry_id}")
        return cast(DHEConnectRuntimeData, runtime)
    if len(runtimes) == 1:
        return cast(DHEConnectRuntimeData, next(iter(runtimes.values())))
    raise HomeAssistantError(
        "Multiple DHE Connect devices are configured; set entry_id in the service call."
    )


async def _weather_results_from_service_input(
    client: DHEClient,
    data: dict[str, Any],
    *,
    missing_country_error: str,
) -> list[dict[str, Any]]:
    """Resolve weather result candidates from service input."""
    if data.get(ATTR_NAME):
        if ATTR_COUNTRY_ID not in data:
            raise HomeAssistantError(missing_country_error)
        searched = await _run_dhe_service_action(
            client.search_weather_locations(
                data[ATTR_NAME],
                data[ATTR_COUNTRY_ID],
            ),
            "Could not search DHE weather locations",
        )
        return _weather_locations(searched)
    return _weather_locations(client.last_weather_state.get("forecast_results"))


def _select_weather_location(
    state: dict[str, Any],
    results: list[dict[str, Any]],
    location_id: str | None,
    result_number: int,
    *,
    allow_raw_location_id: bool = False,
) -> dict[str, Any] | str:
    candidates = list(results)
    candidates.extend(_weather_locations(state.get("favorites")))
    current_location = state.get("location")
    if isinstance(current_location, dict):
        candidates.append(current_location)

    if location_id:
        for location in candidates:
            if str(location.get("LocationId", "")) == str(location_id):
                return location
        if allow_raw_location_id:
            return str(location_id)
        raise HomeAssistantError(f"Weather location_id not found: {location_id}")

    if result_number > len(results):
        raise HomeAssistantError(
            f"Weather search result {result_number} is not available"
        )
    return results[result_number - 1]


def _weather_location_payload(location: dict[str, Any] | str) -> dict[str, Any]:
    """Return a weather location payload with LocationId for client actions."""
    if isinstance(location, dict):
        return location
    location_id = str(location or "").strip()
    if not location_id:
        raise HomeAssistantError("Weather location_id must not be empty")
    return {"LocationId": location_id}


def _weather_locations(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
