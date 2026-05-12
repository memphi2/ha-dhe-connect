"""Pure mapping helpers for config and options flows."""

from __future__ import annotations

from typing import Any


def weather_country_options(countries: list[dict[str, Any]]) -> dict[str, str]:
    """Build a sorted select list for DHE weather countries."""
    options: dict[str, str] = {}
    for country in countries:
        country_id = country.get("CountryId")
        name = str(country.get("Country") or "").strip()
        if country_id is None or not name:
            continue
        try:
            country_id_key = str(int(country_id))
        except (TypeError, ValueError):
            continue
        options[country_id_key] = f"{name} ({country_id_key})"
    return dict(sorted(options.items(), key=lambda item: item[1].casefold()))


def default_weather_country_id(
    country_options: dict[str, str],
    preferred_country_id: int,
) -> str:
    """Return a sensible default country id for the weather favorite search."""
    preferred = str(preferred_country_id)
    if preferred in country_options:
        return preferred
    if country_options:
        return next(iter(country_options))
    return preferred


def weather_location_label(location: dict[str, Any]) -> str:
    """Return a readable label for a weather search result."""
    name = str(location.get("Name") or "").strip()
    country = str(location.get("Country") or "").strip()
    location_id = str(location.get("LocationId") or "").strip()

    if name and country:
        return f"{name}, {country}"
    if name:
        return name
    if location_id:
        return location_id
    return "Unknown location"


def weather_result_options(
    results: list[dict[str, Any]],
    *,
    max_options: int,
) -> dict[str, str]:
    """Build a select list for weather search results."""
    options: dict[str, str] = {}
    for index, location in enumerate(results[:max_options]):
        options[str(index)] = weather_location_label(location)
    return options


def radio_catalog_options(values: list[str]) -> dict[str, str]:
    """Build a select list for a DHE radio search catalog."""
    options: dict[str, str] = {}
    for item in values:
        value = str(item).strip()
        if value:
            options[value] = value
    return options


def default_radio_catalog_value(
    search_type: str,
    catalog_options: dict[str, str],
    default_values: dict[str, str],
) -> str:
    """Return a sensible default value for radio station search."""
    preferred = default_values.get(search_type, "")
    if preferred in catalog_options:
        return preferred
    if catalog_options:
        return next(iter(catalog_options))
    return preferred


def radio_station_label(station: dict[str, Any]) -> str:
    """Return a readable label for a radio station search result."""
    name = str(station.get("Name") or station.get("name") or "").strip()
    station_id = station.get("Id", station.get("id"))
    city = str(station.get("City") or station.get("city") or "").strip()
    country = str(station.get("Country") or station.get("country") or "").strip()
    description = str(
        station.get("ShortDescription")
        or station.get("shortDescription")
        or ""
    ).strip()

    label = name or (str(station_id) if station_id is not None else "Unknown station")
    details = ", ".join(part for part in (city, country) if part)
    if details:
        label = f"{label} - {details}"
    elif description:
        label = f"{label} - {description}"
    if station_id is not None:
        label = f"{label} ({station_id})"
    return label[:255]


def radio_result_options(
    results: list[dict[str, Any]],
    *,
    max_options: int,
) -> dict[str, str]:
    """Build a select list for radio station search results."""
    options: dict[str, str] = {}
    for index, station in enumerate(results[:max_options]):
        options[str(index)] = radio_station_label(station)
    return options


def filter_radio_results_by_text(
    results: list[dict[str, Any]],
    search_text: str,
) -> list[dict[str, Any]]:
    """Return station results matching the entered text when possible."""
    needle = search_text.casefold().strip()
    if needle == "*":
        return results
    if not needle:
        return results

    filtered: list[dict[str, Any]] = []
    for station in results:
        genres = station.get("Genres", station.get("genres", []))
        genre_text = (
            " ".join(str(genre) for genre in genres)
            if isinstance(genres, list)
            else str(genres or "")
        )
        searchable_parts = [
            station.get("Name"),
            station.get("name"),
            station.get("ShortDescription"),
            station.get("shortDescription"),
            station.get("City"),
            station.get("city"),
            station.get("Country"),
            station.get("country"),
            genre_text,
        ]
        searchable = " ".join(
            str(part).casefold() for part in searchable_parts if part
        )
        if needle in searchable:
            filtered.append(station)
    return filtered
