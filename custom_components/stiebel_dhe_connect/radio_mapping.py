"""Pure radio display mapping helpers."""

from __future__ import annotations

from collections import Counter
from typing import Any


def radio_attributes(state: dict[str, Any]) -> dict[str, Any]:
    """Build Home Assistant media-player attributes from DHE radio state."""
    station = state.get("station")
    attributes: dict[str, Any] = {"radio_path": "ste.app.radio"}

    if isinstance(station, dict):
        attributes["station_id"] = station_id(station)
        attributes["station_name"] = station_name(station)
        station_city = station_text(station, "City")
        station_country = station_text(station, "Country")
        station_genres = station.get("Genres", station.get("genres"))
        if station_city:
            attributes["station_city"] = station_city
        if station_country:
            attributes["station_country"] = station_country
        if isinstance(station_genres, list):
            attributes["station_genres"] = [str(genre) for genre in station_genres]

    title = state.get("title")
    if title not in (None, ""):
        attributes["title"] = title

    bluetooth_paired = state.get("paired")
    if bluetooth_paired not in (None, ""):
        attributes["bluetooth_paired"] = bluetooth_paired

    favorites = stations(state.get("favorites"))
    if favorites:
        attributes["favorite_count"] = len(favorites)
        attributes["favorites"] = [
            {
                "id": station_id(favorite),
                "name": station_name(favorite),
            }
            for favorite in favorites
        ]

    return attributes


def source_option_map(stations_value: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build source options, disambiguating duplicate station labels by id."""
    labels = [source_label(station) for station in stations_value]
    label_counts = Counter(labels)
    options: dict[str, dict[str, Any]] = {}
    seen_options: set[str] = set()

    for station, label in zip(stations_value, labels, strict=True):
        current_station_id = station_id(station)
        option = label
        if label_counts[label] > 1 and current_station_id is not None:
            option = f"{label} ({current_station_id})"
        if option in seen_options:
            suffix = 2
            option = f"{label} #{suffix}"
            while option in seen_options:
                suffix += 1
                option = f"{label} #{suffix}"
        seen_options.add(option)
        options[option] = station
    return options


def source_option_map_for_state(
    state: dict[str, Any],
    current_sources: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build source options while keeping startup radio states usable."""
    station = state.get("station")
    if "favorites" in state:
        favorites = stations(state.get("favorites"))
        if favorites:
            return source_option_map(favorites)
        if isinstance(station, dict):
            return source_option_map([station])
        return {}

    if isinstance(station, dict):
        if current_sources:
            return source_option_map(_merge_current_station(current_sources, station))
        return source_option_map([station])

    if current_sources:
        return {option: dict(station) for option, station in current_sources.items()}

    return {}


def _merge_current_station(
    current_sources: dict[str, dict[str, Any]],
    station: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return current sources with the latest station payload upserted."""
    current_station_id = station_id(station)
    current_station_name = station_name(station)
    merged: list[dict[str, Any]] = []

    for source_station in current_sources.values():
        if current_station_id is not None:
            if station_id(source_station) == current_station_id:
                continue
        elif station_name(source_station) == current_station_name:
            continue
        merged.append(dict(source_station))

    merged.append(dict(station))
    return merged


def source_for_station(
    station: Any,
    sources_by_option: dict[str, dict[str, Any]],
) -> str | None:
    """Return the source option label for the current station."""
    current_station_id = station_id(station)
    if current_station_id is None:
        return station_name(station)

    for option, source_station in sources_by_option.items():
        if station_id(source_station) == current_station_id:
            return option
    return station_name(station)


def source_for_state(
    station: Any,
    sources_by_option: dict[str, dict[str, Any]],
    current_source: str | None = None,
) -> str | None:
    """Return the active source, falling back to a stable navigation anchor."""
    source = source_for_station(station, sources_by_option)
    if source is not None:
        return source
    if current_source in sources_by_option:
        return current_source
    return next(iter(sources_by_option), None)


def source_label(station: dict[str, Any]) -> str:
    """Return a source label for one station."""
    return station_name(station) or "Unknown station"


def stations(value: Any) -> list[dict[str, Any]]:
    """Normalize a station list for media-player source handling."""
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def media_title(state: dict[str, Any], station: dict[str, Any]) -> str | None:
    """Return current media title, falling back to station description/name."""
    title = state.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    short_description = station_text(station, "ShortDescription")
    if short_description:
        return short_description
    return station_name(station)


def station_name(station: Any) -> str | None:
    """Return a station display name."""
    if not isinstance(station, dict):
        return None
    name = station_text(station, "Name")
    if name:
        return name
    current_station_id = station_id(station)
    return str(current_station_id) if current_station_id is not None else None


def station_id(station: Any) -> int | None:
    """Return a station id from upper- or lower-case payload keys."""
    if not isinstance(station, dict):
        return None
    current_station_id = station.get("Id", station.get("id"))
    if current_station_id is None:
        return None
    try:
        return int(current_station_id)
    except (TypeError, ValueError):
        return None


def station_logo_url(station: dict[str, Any]) -> str | None:
    """Return the best station logo URL."""
    url = (
        station_text(station, "Logo175Url")
        or station_text(station, "Logo100Url")
        or station_text(station, "Logo44Url")
    )
    if url and url.startswith("//"):
        return f"https:{url}"
    return url


def station_text(station: dict[str, Any], key: str) -> str | None:
    """Return text from upper- or lower-case DHE station keys."""
    value = station.get(key, station.get(key[:1].lower() + key[1:]))
    if value in (None, ""):
        return None
    return str(value)
