"""Stiebel DHE Connect custom integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .client import DHEClient
from .const import (
    DEFAULT_NAME,
    DEFAULT_PORT,
    DOMAIN,
    PLATFORMS,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_SEARCH_WEATHER_LOCATION = "search_weather_location"
SERVICE_TOGGLE_WEATHER_FAVORITE = "toggle_weather_favorite"
SERVICE_SELECT_WEATHER_LOCATION = "select_weather_location"

ATTR_COUNTRY_ID = "country_id"
ATTR_LOCATION_ID = "location_id"
ATTR_NAME = "name"
ATTR_RESULT_NUMBER = "result_number"

WEATHER_SEARCH_SCHEMA = vol.Schema({
    vol.Required(ATTR_NAME): cv.string,
    vol.Required(ATTR_COUNTRY_ID): vol.Coerce(int),
})
WEATHER_LOCATION_ACTION_SCHEMA = vol.Schema({
    vol.Optional(ATTR_NAME): cv.string,
    vol.Optional(ATTR_COUNTRY_ID): vol.Coerce(int),
    vol.Optional(ATTR_LOCATION_ID): cv.string,
    vol.Optional(ATTR_RESULT_NUMBER, default=1): vol.All(
        vol.Coerce(int),
        vol.Range(min=1, max=20),
    ),
})
WEATHER_TOGGLE_FAVORITE_SCHEMA = WEATHER_LOCATION_ACTION_SCHEMA
WEATHER_SELECT_LOCATION_SCHEMA = WEATHER_LOCATION_ACTION_SCHEMA
LEGACY_ENTITY_SUFFIXES_TO_REMOVE = (
    "online",
    "currency",
    "electricity_price",
    "water_price",
    "co2_emission",
    "unknown_odb_33",
    "setpoint_below_inlet",
)
LEGACY_ENTITY_KEYWORDS_TO_REMOVE = (
    "currency",
    "electricity_price",
    "water_price",
    "co2_emission",
)


@dataclass
class DHEConnectRuntimeData:
    """Runtime data for the integration."""

    client: DHEClient
    name: str


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Stiebel DHE Connect from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    data = {**entry.data, **entry.options}
    host = data[CONF_HOST]
    port = int(data.get(CONF_PORT, DEFAULT_PORT))
    name = data.get(CONF_NAME, DEFAULT_NAME)

    token_file = ".storage/stiebel_dhe_connect_token.txt"

    client = DHEClient(
        hass=hass,
        host=host,
        port=port,
        token_file=token_file,
        name="Home Assistant",
    )

    hass.data[DOMAIN][entry.entry_id] = DHEConnectRuntimeData(
        client=client,
        name=name,
    )
    _async_cleanup_legacy_entities(hass, entry)

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        raise
    _async_register_services(hass)
    _start_client_background(hass, client)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


def _async_cleanup_legacy_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove stale registry entities from older integration revisions."""
    entity_registry = er.async_get(hass)
    unique_id_prefix = f"stiebel_dhe_connect_{entry.entry_id}_"
    unique_ids_to_remove = {
        f"{unique_id_prefix}{suffix}"
        for suffix in LEGACY_ENTITY_SUFFIXES_TO_REMOVE
    }

    for entity_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        unique_id = str(entity_entry.unique_id or "")
        is_explicit_legacy_id = unique_id in unique_ids_to_remove
        is_legacy_cost_entity = (
            unique_id.startswith(unique_id_prefix)
            and entity_entry.platform in {"number", "select"}
            and any(keyword in unique_id for keyword in LEGACY_ENTITY_KEYWORDS_TO_REMOVE)
        )
        if is_explicit_legacy_id or is_legacy_cost_entity:
            _LOGGER.debug(
                "Removing stale entity registry entry unique_id=%s entity_id=%s",
                unique_id,
                entity_entry.entity_id,
            )
            entity_registry.async_remove(entity_entry.entity_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unloaded:
        if runtime is not None:
            await runtime.client.stop()
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if not hass.data.get(DOMAIN):
            _async_unregister_services(hass)

    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _start_client_background(hass: HomeAssistant, client: DHEClient) -> None:
    """Start the persistent DHE session without blocking entity setup."""
    create_background_task = getattr(hass, "async_create_background_task", None)
    if create_background_task is not None:
        create_background_task(client.start(), "stiebel_dhe_connect_start")
    else:
        hass.async_create_task(client.start(), name="stiebel_dhe_connect_start")


def _async_register_services(hass: HomeAssistant) -> None:
    """Register integration services once."""
    async def async_search_weather_location(call: ServiceCall) -> None:
        runtime = _single_runtime(hass)
        await runtime.client.search_weather_locations(
            call.data[ATTR_NAME],
            call.data[ATTR_COUNTRY_ID],
        )

    async def async_toggle_weather_favorite(call: ServiceCall) -> None:
        runtime = _single_runtime(hass)
        client = runtime.client
        data = call.data
        if data.get(ATTR_NAME):
            if ATTR_COUNTRY_ID not in data:
                raise HomeAssistantError(
                    "country_id is required when toggling a weather favorite by name"
                )
            results = await client.search_weather_locations(
                data[ATTR_NAME],
                data[ATTR_COUNTRY_ID],
            )
        else:
            results = _weather_locations(client.last_weather_state.get("forecast_results"))

        location = _select_weather_location(
            client.last_weather_state,
            results,
            data.get(ATTR_LOCATION_ID),
            data[ATTR_RESULT_NUMBER],
        )
        await client.toggle_weather_favorite(location)

    async def async_select_weather_location(call: ServiceCall) -> None:
        runtime = _single_runtime(hass)
        client = runtime.client
        data = call.data
        if data.get(ATTR_NAME):
            if ATTR_COUNTRY_ID not in data:
                raise HomeAssistantError(
                    "country_id is required when selecting a weather location by name"
                )
            results = await client.search_weather_locations(
                data[ATTR_NAME],
                data[ATTR_COUNTRY_ID],
            )
        else:
            results = _weather_locations(client.last_weather_state.get("forecast_results"))

        location = _select_weather_location(
            client.last_weather_state,
            results,
            data.get(ATTR_LOCATION_ID),
            data[ATTR_RESULT_NUMBER],
            allow_raw_location_id=True,
        )
        await client.select_weather_location(location)

    if not hass.services.has_service(DOMAIN, SERVICE_SEARCH_WEATHER_LOCATION):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SEARCH_WEATHER_LOCATION,
            async_search_weather_location,
            schema=WEATHER_SEARCH_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_TOGGLE_WEATHER_FAVORITE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_TOGGLE_WEATHER_FAVORITE,
            async_toggle_weather_favorite,
            schema=WEATHER_TOGGLE_FAVORITE_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_SELECT_WEATHER_LOCATION):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SELECT_WEATHER_LOCATION,
            async_select_weather_location,
            schema=WEATHER_SELECT_LOCATION_SCHEMA,
        )


def _async_unregister_services(hass: HomeAssistant) -> None:
    """Remove integration services when the last entry unloads."""
    for service in (
        SERVICE_SEARCH_WEATHER_LOCATION,
        SERVICE_TOGGLE_WEATHER_FAVORITE,
        SERVICE_SELECT_WEATHER_LOCATION,
    ):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)


def _single_runtime(hass: HomeAssistant) -> DHEConnectRuntimeData:
    """Return the single configured runtime data."""
    runtimes = hass.data.get(DOMAIN) or {}
    if not runtimes:
        raise HomeAssistantError("Stiebel DHE Connect is not loaded")
    return next(iter(runtimes.values()))


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


def _weather_locations(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
