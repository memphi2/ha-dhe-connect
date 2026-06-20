"""Pure protocol mapping helpers for the DHE client."""

from __future__ import annotations

from typing import Any

DEVICE_STATUS_NORMAL = "normal"
DEVICE_STATUS_WATER_RUNNING = "status_2"
DEVICE_STATUS_SERVICE_REQUIRED = "service_required"
DEVICE_STATUS_UNKNOWN = "unknown"
DEVICE_STATUS_OPTIONS = (
    "status_0",
    DEVICE_STATUS_NORMAL,
    DEVICE_STATUS_WATER_RUNNING,
    DEVICE_STATUS_SERVICE_REQUIRED,
    "status_4",
    "status_5",
    "status_6",
    "status_7",
    "status_8",
    DEVICE_STATUS_UNKNOWN,
)


def copy_json_like_value(value: Any) -> Any:
    """Return a recursive copy of JSON-like data structures."""
    if isinstance(value, dict):
        return {
            key: copy_json_like_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [copy_json_like_value(item) for item in value]
    return value


def copy_dict_items(value: Any) -> list[dict[str, Any]]:
    """Return copied dict entries from a list-like protocol value."""
    if not isinstance(value, list):
        return []
    return [
        copy_json_like_value(item)
        for item in value
        if isinstance(item, dict)
    ]


def normalize_weather_value(raw_value: dict[str, Any]) -> dict[str, Any]:
    """Normalize the DHE weather location payload into client state."""
    state: dict[str, Any] = {}

    location = raw_value.get("Location")
    if isinstance(location, dict):
        state["location"] = copy_json_like_value(location)

    complete_days = raw_value.get("CompleteDays")
    if isinstance(complete_days, list):
        state["complete_days"] = copy_dict_items(complete_days)

    simple_days = raw_value.get("SimpleDays")
    if isinstance(simple_days, list):
        state["simple_days"] = copy_dict_items(simple_days)

    return state


def normalize_weather_locations_value(raw_value: Any) -> list[dict[str, Any]] | None:
    """Normalize a DHE weather location list."""
    if not isinstance(raw_value, list):
        return None
    return copy_dict_items(raw_value)


def normalize_weather_favorites_value(raw_value: Any) -> list[dict[str, Any]] | None:
    """Normalize a DHE weather favorites list."""
    return normalize_weather_locations_value(raw_value)


def normalize_radio_stations_value(raw_value: Any) -> list[dict[str, Any]] | None:
    """Normalize a DHE radio station list."""
    if not isinstance(raw_value, list):
        return None
    return copy_dict_items(raw_value)


def normalize_radio_string_catalog(raw_value: Any) -> list[str] | None:
    """Normalize a DHE radio string catalog."""
    if not isinstance(raw_value, list):
        return None

    values: list[str] = []
    for item in raw_value:
        if item is None:
            continue
        value = str(item).strip()
        if value:
            values.append(value)
    return values


def radio_station_id(station: dict[str, Any]) -> int | None:
    """Return the normalized station id from a DHE radio station payload."""
    current_station_id = station.get("Id", station.get("id"))
    if current_station_id is None:
        return None
    try:
        return int(current_station_id)
    except (TypeError, ValueError):
        return None


def radio_station_in_list(
    station_id: int,
    stations: list[dict[str, Any]],
) -> bool:
    """Return whether the station id exists in a DHE station list."""
    return any(radio_station_id(candidate) == station_id for candidate in stations)


def radio_station_input_id(value: dict[str, Any] | int | str) -> int | None:
    """Return a normalized station id from user input."""
    if isinstance(value, dict):
        return radio_station_id(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def weather_location_id(location: dict[str, Any]) -> str:
    """Return the normalized DHE weather location id."""
    return str(location.get("LocationId", "")).strip()


def weather_location_has_id(value: Any) -> bool:
    """Return whether an input value is a weather location payload with LocationId."""
    return isinstance(value, dict) and bool(weather_location_id(value))


def weather_location_in_list(
    location: dict[str, Any],
    locations: list[dict[str, Any]],
) -> bool:
    """Return whether the location exists in a DHE location list."""
    location_id = weather_location_id(location)
    if not location_id:
        return False
    return any(weather_location_id(candidate) == location_id for candidate in locations)


def device_status_code(raw_value: Any) -> int | None:
    """Return the DHE device status code as an integer."""
    if raw_value is None or isinstance(raw_value, bool):
        return None
    try:
        return int(float(raw_value))
    except (TypeError, ValueError):
        return None


def device_status_key(raw_value: Any) -> str:
    """Return the Home Assistant enum state for a DHE device status code."""
    code = device_status_code(raw_value)
    if code == 1:
        return DEVICE_STATUS_NORMAL
    if code == 3:
        return DEVICE_STATUS_SERVICE_REQUIRED
    if code is not None and 0 <= code <= 8:
        return f"status_{code}"
    return DEVICE_STATUS_UNKNOWN


def device_status_problem(raw_value: Any) -> bool:
    """Return whether the status code should be shown as a device problem."""
    return device_status_key(raw_value) == DEVICE_STATUS_SERVICE_REQUIRED
