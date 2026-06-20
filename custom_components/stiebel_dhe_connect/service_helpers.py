"""Shared service metadata and validation helpers."""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from typing import Any, Protocol

from .action_error_helpers import run_dhe_action, translated_homeassistant_error

ATTR_COUNTRY_ID = "country_id"
ATTR_ENTRY_ID = "entry_id"
ATTR_LOCATION_ID = "location_id"
ATTR_NAME = "name"
ATTR_RESULT_NUMBER = "result_number"

WEATHER_RESULT_NUMBER_MAX = 50


class WeatherServiceClient(Protocol):
    """Client surface needed by weather service helpers."""

    @property
    def last_weather_state(self) -> Mapping[str, Any]:
        """Return the latest normalized weather runtime state."""

    def search_weather_locations(
        self,
        name: str,
        country_id: int | float | str,
    ) -> Awaitable[list[dict[str, Any]]]:
        """Search weather locations on the DHE."""


async def weather_results_from_service_input(
    client: WeatherServiceClient,
    data: dict[str, Any],
    *,
    missing_country_error: str,
) -> list[dict[str, Any]]:
    """Resolve weather result candidates from service input."""
    if data.get(ATTR_NAME):
        if ATTR_COUNTRY_ID not in data:
            raise translated_homeassistant_error(
                missing_country_error,
                translation_key="dhe_weather_country_required",
                translation_placeholders={"error": missing_country_error},
            )
        searched = await run_dhe_action(
            client.search_weather_locations(
                data[ATTR_NAME],
                data[ATTR_COUNTRY_ID],
            ),
            "Could not search DHE weather locations",
        )
        return weather_locations(searched)
    return weather_locations(client.last_weather_state.get("forecast_results"))


def select_weather_location(
    state: Mapping[str, Any],
    results: list[dict[str, Any]],
    location_id: str | None,
    result_number: int,
    *,
    allow_raw_location_id: bool = False,
) -> dict[str, Any] | str:
    """Resolve a weather location from search results, favorites or raw ID."""
    candidates = list(results)
    candidates.extend(weather_locations(state.get("favorites")))
    current_location = state.get("location")
    if isinstance(current_location, dict):
        candidates.append(current_location)

    if location_id:
        for location in candidates:
            if str(location.get("LocationId", "")) == str(location_id):
                return location
        if allow_raw_location_id:
            return str(location_id)
        raise translated_homeassistant_error(
            f"Weather location_id not found: {location_id}",
            translation_key="dhe_weather_location_not_found",
            translation_placeholders={"location_id": str(location_id)},
        )

    if result_number < 1 or result_number > len(results):
        raise translated_homeassistant_error(
            f"Weather search result {result_number} is not available",
            translation_key="dhe_weather_result_unavailable",
            translation_placeholders={"result_number": str(result_number)},
        )
    return results[result_number - 1]


def weather_location_payload(location: dict[str, Any] | str) -> dict[str, Any]:
    """Return a weather location payload with LocationId for client actions."""
    if isinstance(location, dict):
        return location
    location_id = str(location or "").strip()
    if not location_id:
        raise translated_homeassistant_error(
            "Weather location_id must not be empty",
            translation_key="dhe_weather_location_id_empty",
        )
    return {"LocationId": location_id}


def weather_locations(value: Any) -> list[dict[str, Any]]:
    """Return only dict-shaped weather locations from a DHE payload."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def service_result_number(data: Mapping[str, Any]) -> int:
    """Return one validated 1-based weather result number from service data."""
    raw_result_number = data.get(ATTR_RESULT_NUMBER, 1)
    try:
        result_number = int(raw_result_number)
    except (TypeError, ValueError) as err:
        raise translated_homeassistant_error(
            f"Weather search result {raw_result_number!r} is invalid",
            translation_key="dhe_weather_result_unavailable",
            translation_placeholders={"result_number": str(raw_result_number)},
        ) from err
    if result_number < 1 or result_number > WEATHER_RESULT_NUMBER_MAX:
        raise translated_homeassistant_error(
            f"Weather search result {result_number} is not available",
            translation_key="dhe_weather_result_unavailable",
            translation_placeholders={"result_number": str(result_number)},
        )
    return result_number
