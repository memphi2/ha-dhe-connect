"""DHE Connect custom integration."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass
from typing import Any, cast

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .action_error_helpers import run_dhe_action
from .async_helpers import cancel_task_if_pending
from .client import DHEClient
from .config_entry_helpers import merged_entry_data, entry_target
from .connection_probe import async_can_connect as _async_can_connect
from .const import (
    DEFAULT_NAME,
    DOMAIN,
    PLATFORMS,
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
    host, port = target
    name = data.get(CONF_NAME, DEFAULT_NAME)

    if not await _async_can_connect(hass, host, port):
        raise ConfigEntryNotReady("Could not connect to DHE before setup")

    token_file = _token_file_for_entry(entry)
    await _async_migrate_legacy_token_if_needed(hass, entry, token_file)

    client = DHEClient(
        hass=hass,
        host=host,
        port=port,
        token_file=token_file,
        name="Home Assistant",
    )
    client.legacy_device_identifier = _legacy_device_identifier_for_entry(
        hass,
        entry,
        host,
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
    _async_register_services(hass)
    runtime.start_task = _start_client_background(hass, client)
    entry.async_on_unload(runtime.start_task.cancel)
    _async_register_reauth_trigger(hass, entry, client)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


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


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    runtime = getattr(entry, "runtime_data", None)
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

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
    client: DHEClient,
) -> asyncio.Task[Any]:
    """Start the persistent DHE session without blocking entity setup."""
    create_background_task = getattr(hass, "async_create_background_task", None)
    if create_background_task is not None:
        return create_background_task(client.start(), "stiebel_dhe_connect_start")
    return hass.async_create_task(client.start(), name="stiebel_dhe_connect_start")


def _async_register_reauth_trigger(
    hass: HomeAssistant,
    entry: ConfigEntry,
    client: DHEClient,
) -> None:
    """Start Home Assistant reauth once the runtime reports auth failure."""
    reauth_started = False

    @callback
    def _handle_diagnostic_update(state: dict[str, Any]) -> None:
        nonlocal reauth_started
        if reauth_started:
            return
        if state.get("auth_failure") is True or state.get("connection_state") == "auth_failed":
            reauth_started = True
            entry.async_start_reauth(hass, data=dict(entry.data))

    entry.async_on_unload(client.add_diagnostic_callback(_handle_diagnostic_update))


def _async_register_services(hass: HomeAssistant) -> None:
    """Register integration services once."""

    async def async_search_weather_location(call: ServiceCall) -> None:
        runtime = _resolve_runtime(hass, call.data.get(ATTR_ENTRY_ID))
        await _run_dhe_service_action(
            runtime.client.search_weather_locations(
                call.data[ATTR_NAME],
                call.data[ATTR_COUNTRY_ID],
            ),
            "Could not search DHE weather locations",
        )

    async def async_toggle_weather_favorite(call: ServiceCall) -> None:
        runtime = _resolve_runtime(hass, call.data.get(ATTR_ENTRY_ID))
        client = runtime.client
        data = call.data
        results = await _weather_results_from_service_input(
            client,
            data,
            missing_country_error=(
                "country_id is required when toggling a weather favorite by name"
            ),
        )

        location = _select_weather_location(
            client.last_weather_state,
            results,
            data.get(ATTR_LOCATION_ID),
            data[ATTR_RESULT_NUMBER],
            allow_raw_location_id=True,
        )
        await _run_dhe_service_action(
            client.toggle_weather_favorite(_weather_location_payload(location)),
            "Could not toggle DHE weather favorite",
        )

    async def async_add_weather_favorite(call: ServiceCall) -> None:
        runtime = _resolve_runtime(hass, call.data.get(ATTR_ENTRY_ID))
        client = runtime.client
        data = call.data
        results = await _weather_results_from_service_input(
            client,
            data,
            missing_country_error=(
                "country_id is required when adding a weather favorite by name"
            ),
        )

        location = _select_weather_location(
            client.last_weather_state,
            results,
            data.get(ATTR_LOCATION_ID),
            data[ATTR_RESULT_NUMBER],
            allow_raw_location_id=True,
        )
        await _run_dhe_service_action(
            client.add_weather_favorite(_weather_location_payload(location)),
            "Could not add DHE weather favorite",
        )

    async def async_remove_weather_favorite(call: ServiceCall) -> None:
        runtime = _resolve_runtime(hass, call.data.get(ATTR_ENTRY_ID))
        client = runtime.client
        data = call.data
        results = await _weather_results_from_service_input(
            client,
            data,
            missing_country_error=(
                "country_id is required when removing a weather favorite by name"
            ),
        )

        location = _select_weather_location(
            client.last_weather_state,
            results,
            data.get(ATTR_LOCATION_ID),
            data[ATTR_RESULT_NUMBER],
            allow_raw_location_id=True,
        )
        await _run_dhe_service_action(
            client.remove_weather_favorite(_weather_location_payload(location)),
            "Could not remove DHE weather favorite",
        )

    async def async_select_weather_location(call: ServiceCall) -> None:
        runtime = _resolve_runtime(hass, call.data.get(ATTR_ENTRY_ID))
        client = runtime.client
        data = call.data
        results = await _weather_results_from_service_input(
            client,
            data,
            missing_country_error=(
                "country_id is required when selecting a weather location by name"
            ),
        )

        location = _select_weather_location(
            client.last_weather_state,
            results,
            data.get(ATTR_LOCATION_ID),
            data[ATTR_RESULT_NUMBER],
            allow_raw_location_id=True,
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
        return await _run_dhe_service_action(
            client.search_weather_locations(
                data[ATTR_NAME],
                data[ATTR_COUNTRY_ID],
            ),
            "Could not search DHE weather locations",
        )
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
