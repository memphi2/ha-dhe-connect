"""DHE Connect custom integration."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, SOURCE_REAUTH
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from .action_error_helpers import translated_homeassistant_error
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
from .entity_helpers import device_registry_model, device_registry_sw_version
from .protocol import ID_DEVICE_INFO
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
from .services import (
    async_register_services as _async_register_services,
    async_unregister_services as _async_unregister_services,
)
from .token_file_helpers import (
    LEGACY_TOKEN_FILE,
    legacy_token_file_for_entry,
    token_file_for_target,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
STALE_SENSOR_STATISTIC_TRANSLATION_KEYS = frozenset(
    {
        "odb_possible_energy_saving",
        "odb_actual_water_saving",
    }
)
WELLNESS_ENTITY_KEY_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("wellness_winter_refresh", "wellness_winter_pick_me_up"),
    ("wellness_circulation_support", "wellness_circulation_boost"),
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
    _async_register_services(hass, _resolve_runtime)
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
        raise translated_homeassistant_error(
            "Invalid DHE host/port in config entry",
            translation_key="dhe_invalid_config_entry",
        )
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
        _async_migrate_wellness_switch_unique_ids(hass, entry)
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
    _async_register_device_registry_updates(hass, entry, client)
    _async_clear_stale_sensor_statistic_issues(hass, entry)
    _async_register_services(hass, _resolve_runtime)
    _async_register_reauth_trigger(hass, entry, client)
    runtime.start_task = _start_client_background(hass, entry, client)
    entry.async_on_unload(task_cancel_callback(runtime.start_task))
    async_delete_repair_issues(hass, entry.entry_id)
    _async_clear_config_entry_reauth(hass, entry)
    _async_schedule_config_entry_reauth_clear(hass, entry)
    _async_schedule_connected_issue_cleanup(hass, entry, client)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


def _async_migrate_wellness_switch_unique_ids(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Migrate legacy wellness switch unique IDs to canonical program keys."""
    entity_registry = er.async_get(hass)
    entities = list(
        er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    )
    if not entities:
        return

    prefix = f"{DOMAIN}_{entry.entry_id}_"
    unique_id_migrations = {
        f"{prefix}{old_key}": f"{prefix}{new_key}"
        for old_key, new_key in WELLNESS_ENTITY_KEY_MIGRATIONS
    }
    unique_ids = {entity.unique_id for entity in entities}
    migrated = 0

    for entity in entities:
        target_unique_id = unique_id_migrations.get(entity.unique_id)
        if target_unique_id is None:
            continue
        if target_unique_id in unique_ids:
            _LOGGER.debug(
                "Skipping wellness unique-id migration for %s because %s already exists",
                entity.entity_id,
                target_unique_id,
            )
            continue
        entity_registry.async_update_entity(
            entity.entity_id,
            new_unique_id=target_unique_id,
        )
        unique_ids.discard(entity.unique_id)
        unique_ids.add(target_unique_id)
        migrated += 1

    if migrated:
        _LOGGER.debug(
            "Migrated %s wellness switch unique-id(s) for config entry %s",
            migrated,
            entry.entry_id,
        )


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


def _async_register_device_registry_updates(
    hass: HomeAssistant,
    entry: ConfigEntry,
    client: DHEClient,
) -> None:
    """Keep the HA device registry aligned with DHE runtime device metadata."""
    last_metadata: tuple[str, str | None] | None = None

    @callback
    def _apply_device_registry_update() -> None:
        nonlocal last_metadata
        metadata = _device_registry_metadata(client)
        if metadata == last_metadata:
            return
        if _async_update_device_registry_info(hass, entry, client, metadata):
            last_metadata = metadata

    @callback
    def _handle_measurement_update(odb_id: int, _value: Any) -> None:
        if odb_id == ID_DEVICE_INFO:
            _apply_device_registry_update()

    _apply_device_registry_update()
    entry.async_on_unload(
        client.add_measurement_callback(_handle_measurement_update, replay=True)
    )


def _device_registry_metadata(client: DHEClient) -> tuple[str, str | None]:
    """Return model and firmware values for the HA device registry."""
    raw_device_info = getattr(client, "last_device_info", {})
    device_info = raw_device_info if isinstance(raw_device_info, Mapping) else {}
    return (
        device_registry_model(device_info),
        device_registry_sw_version(device_info),
    )


def _async_update_device_registry_info(
    hass: HomeAssistant,
    entry: ConfigEntry,
    client: DHEClient,
    metadata: tuple[str, str | None],
) -> bool:
    """Update one HA device registry entry with runtime model/firmware metadata."""
    device_registry = dr.async_get(hass)
    device_entry = _async_entry_device(device_registry, entry, client)
    if device_entry is None:
        return False

    model, sw_version = metadata
    device_registry.async_update_device(
        device_entry.id,
        manufacturer=None,
        model=model,
        sw_version=sw_version,
    )
    return True


def _async_entry_device(
    device_registry: dr.DeviceRegistry,
    entry: ConfigEntry,
    client: DHEClient,
) -> dr.DeviceEntry | None:
    """Return the canonical HA device entry for one DHE config entry."""
    stable_identifier = getattr(client, "device_identifier", None)
    devices = [
        device
        for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id)
        if any(domain == DOMAIN for domain, _identifier in device.identifiers)
    ]
    if not devices:
        return None
    if stable_identifier:
        stable_key = (DOMAIN, stable_identifier)
        if device := next(
            (device for device in devices if stable_key in device.identifiers),
            None,
        ):
            return device
    return devices[0]


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


def _resolve_runtime(
    hass: HomeAssistant,
    entry_id: str | None = None,
) -> DHEConnectRuntimeData:
    """Resolve runtime by entry_id or infer it when only one entry exists."""
    runtimes = dict(iter_loaded_runtime_data(hass))
    if not runtimes:
        raise translated_homeassistant_error(
            "DHE Connect is not loaded",
            translation_key="dhe_not_loaded",
        )
    if entry_id:
        runtime = runtimes.get(entry_id)
        if runtime is None:
            raise translated_homeassistant_error(
                f"DHE Connect entry_id not loaded: {entry_id}",
                translation_key="dhe_entry_not_loaded",
                translation_placeholders={"entry_id": str(entry_id)},
            )
        return cast(DHEConnectRuntimeData, runtime)
    if len(runtimes) == 1:
        return cast(DHEConnectRuntimeData, next(iter(runtimes.values())))
    raise translated_homeassistant_error(
        "Multiple DHE Connect devices are configured; set entry_id in the service call.",
        translation_key="dhe_entry_id_required",
    )
