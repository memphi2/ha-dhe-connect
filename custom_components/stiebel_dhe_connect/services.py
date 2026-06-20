"""Home Assistant services for DHE Connect."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .action_error_helpers import raise_if_dhe_unavailable, run_dhe_action
from .client import DHEClient
from .const import DOMAIN
from .payload_types import WeatherLocationPayload
from .service_helpers import (
    ATTR_COUNTRY_ID,
    ATTR_ENTRY_ID,
    ATTR_LOCATION_ID,
    ATTR_NAME,
    ATTR_RESULT_NUMBER,
    WEATHER_RESULT_NUMBER_MAX,
    service_result_number,
    select_weather_location,
    weather_location_payload,
    weather_results_from_service_input,
)

SERVICE_SEARCH_WEATHER_LOCATION = "search_weather_location"
SERVICE_ADD_WEATHER_FAVORITE = "add_weather_favorite"
SERVICE_TOGGLE_WEATHER_FAVORITE = "toggle_weather_favorite"
SERVICE_REMOVE_WEATHER_FAVORITE = "remove_weather_favorite"
SERVICE_SELECT_WEATHER_LOCATION = "select_weather_location"

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


class DHEConnectRuntime(Protocol):
    """Runtime surface needed by service handlers."""

    client: DHEClient


RuntimeResolver = Callable[[HomeAssistant, str | None], DHEConnectRuntime]


def async_register_services(
    hass: HomeAssistant,
    runtime_resolver: RuntimeResolver,
) -> None:
    """Register integration services once."""

    async def _resolve_weather_location_for_service(
        call: ServiceCall,
        *,
        unavailable_message: str,
        missing_country_error: str,
    ) -> tuple[DHEClient, WeatherLocationPayload | str]:
        """Resolve one weather location payload from a service call."""
        runtime = runtime_resolver(hass, call.data.get(ATTR_ENTRY_ID))
        client = runtime.client
        raise_if_dhe_unavailable(
            client,
            unavailable_message,
        )
        data = call.data
        results = await weather_results_from_service_input(
            client,
            data,
            missing_country_error=missing_country_error,
        )
        location = select_weather_location(
            client.last_weather_state,
            results,
            data.get(ATTR_LOCATION_ID),
            service_result_number(data),
            allow_raw_location_id=True,
        )
        return client, location

    async def async_search_weather_location(call: ServiceCall) -> None:
        runtime = runtime_resolver(hass, call.data.get(ATTR_ENTRY_ID))
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
            client.toggle_weather_favorite(weather_location_payload(location)),
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
            client.add_weather_favorite(weather_location_payload(location)),
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
            client.remove_weather_favorite(weather_location_payload(location)),
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

    service_registrations: tuple[tuple[str, Callable[[ServiceCall], Any], vol.Schema], ...] = (
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


def async_unregister_services(hass: HomeAssistant) -> None:
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
