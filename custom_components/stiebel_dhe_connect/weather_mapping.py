"""Pure weather display mapping helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any


DHE_WEATHER_ICON_CONDITIONS = {
    1: "sunny",
    2: "sunny",
    3: "partlycloudy",
    4: "partlycloudy",
    5: "cloudy",
    6: "partlycloudy",
    7: "rainy",
    8: "rainy",
}
DHE_WEATHER_ICON_DESCRIPTIONS = {
    1: "clear",
    2: "sunny",
    3: "mostly_sunny",
    4: "partly_cloudy",
    5: "cloudy",
    6: "mostly_cloudy",
    7: "rain",
    8: "rain",
}
WEATHER_DAY_PERIODS = ("morning", "midday", "evening")


def forecast_source_days(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return complete days first, falling back to simple days."""
    days = state.get("complete_days")
    if isinstance(days, list) and days:
        return deduplicate_forecast_days([day for day in days if isinstance(day, dict)])

    days = state.get("simple_days")
    if isinstance(days, list):
        return deduplicate_forecast_days([day for day in days if isinstance(day, dict)])
    return []


def deduplicate_forecast_days(days: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate forecast days by date while preserving order."""
    deduped: list[dict[str, Any]] = []
    seen_dates: set[str] = set()
    for day in days:
        date = day.get("date")
        if isinstance(date, str) and date:
            if date in seen_dates:
                continue
            seen_dates.add(date)
        deduped.append(day)
    return deduped


def forecast_from_day(day: dict[str, Any]) -> dict[str, Any] | None:
    """Build one HA daily forecast item from one DHE day."""
    date = day.get("date")
    if not date:
        return None

    forecast: dict[str, Any] = {"datetime": f"{date}T00:00:00+00:00"}
    condition = daily_condition_from_day(day)
    tmax = number(day.get("tmax"))
    tmin = number(day.get("tmin"))
    precipitation = precipitation_probability(day)
    if condition is not None:
        forecast["condition"] = condition
    if tmax is not None:
        forecast["native_temperature"] = tmax
    if tmin is not None:
        forecast["native_templow"] = tmin
    if precipitation is not None:
        forecast["precipitation_probability"] = precipitation
    return forecast


def weather_attributes(
    state: dict[str, Any],
    today: dict[str, Any],
    forecast: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build HA weather attributes from normalized DHE weather state."""
    current_period = current_weather_period(now)
    attributes: dict[str, Any] = {
        "weather_path": "ste.app.weather",
        "forecast_days": len(forecast),
        "current_period": current_period,
    }
    location = state.get("location")
    if isinstance(location, dict):
        name = weather_location_name(location)
        location_attributes = weather_location_attributes(location)
        if name:
            attributes["location_name"] = name
            attributes["city"] = name
        display_location = weather_location_display(
            name,
            location_attributes.get("country"),
        )
        if display_location:
            attributes["location"] = display_location
            attributes["location_label"] = display_location
        attributes.update(location_attributes)
        favorites = weather_favorites(state)
        if favorites:
            attributes["favorite_count"] = len(favorites)
            attributes["is_favorite"] = location_is_favorite(location, favorites)
            attributes["favorite_locations"] = weather_locations_summary(favorites)
        forecast_results = weather_forecast_results(state)
        if forecast_results:
            attributes["forecast_result_count"] = len(forecast_results)
            attributes["forecast_results"] = weather_locations_summary(forecast_results)

    for key in (
        "icon_id_day",
        "icon_id_morning",
        "icon_id_midday",
        "icon_id_evening",
    ):
        icon_id = int_value(today.get(key))
        if icon_id is not None:
            attributes[key] = icon_id
            description = DHE_WEATHER_ICON_DESCRIPTIONS.get(icon_id)
            if description is not None:
                attributes[key.replace("icon_id_", "icon_")] = description
            precipitation = period_precipitation_probability(today, key)
            condition = condition_from_icon_id(
                icon_id,
                precipitation=precipitation,
            )
            if condition is not None:
                attributes[key.replace("icon_id_", "condition_")] = condition
    precipitation = precipitation_probability(today)
    if precipitation is not None:
        attributes["precipitation_probability"] = precipitation
    country_id = int_value(state.get("country_id"))
    if country_id is not None:
        attributes["selected_country_id"] = country_id
    return attributes


def weather_entity_name(state: dict[str, Any]) -> str | None:
    """Use city/country as weather entity name when available."""
    location = state.get("location")
    if not isinstance(location, dict):
        return None
    name = weather_location_name(location)
    country = location.get("Country")
    return weather_location_display(name, country)


def weather_location_display(name: str | None, country: Any) -> str | None:
    """Return a readable city/country label."""
    country_text = str(country).strip() if country not in (None, "") else ""
    name_text = str(name).strip() if name else ""
    if country_text and name_text:
        return f"{name_text}, {country_text}"
    return name_text or country_text or None


def weather_location_name(location: dict[str, Any]) -> str | None:
    """Return the best display name from a DHE weather location payload."""
    for item in weather_location_name_entries(location):
        name = item.get("Name")
        if name:
            return str(name)
    name = location.get("Name")
    return str(name) if name else None


def weather_location_attributes(location: dict[str, Any]) -> dict[str, Any]:
    """Return normalized attributes from a DHE weather location payload."""
    attributes: dict[str, Any] = {}
    for source_key, attr_key in (
        ("LocationId", "location_id"),
        ("Country", "country"),
        ("CountryId", "country_id"),
        ("SearchType", "search_type"),
    ):
        value = location.get(source_key)
        if value not in (None, ""):
            attributes[attr_key] = value

    search_type = weather_location_search_type(location)
    if search_type is not None:
        attributes["search_type"] = search_type

    names = weather_location_name_entries(location)
    if names:
        attributes["int_names"] = [
            {
                key: item[key]
                for key in ("Name", "Language", "SearchType")
                if isinstance(item, dict) and item.get(key) not in (None, "")
            }
            for item in names
            if isinstance(item, dict)
        ]
    return attributes


def weather_location_name_entries(location: dict[str, Any]) -> list[dict[str, Any]]:
    """Return translated weather location names from the payload."""
    for key in ("IntNames", "I18nNames"):
        names = location.get(key)
        if isinstance(names, list):
            entries = [item for item in names if isinstance(item, dict)]
            if entries:
                return entries
    return []


def weather_location_search_type(location: dict[str, Any]) -> int | None:
    """Return weather search type from the location or translated names."""
    search_type = int_value(location.get("SearchType"))
    if search_type is not None:
        return search_type
    for item in weather_location_name_entries(location):
        search_type = int_value(item.get("SearchType"))
        if search_type is not None:
            return search_type
    return None


def weather_favorites(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return favorite locations from normalized weather state."""
    favorites = state.get("favorites")
    if not isinstance(favorites, list):
        return []
    return [item for item in favorites if isinstance(item, dict)]


def weather_forecast_results(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return forecast search results from normalized weather state."""
    results = state.get("forecast_results")
    if not isinstance(results, list):
        return []
    return [item for item in results if isinstance(item, dict)]


def weather_locations_summary(locations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return compact location summaries for state attributes."""
    summary: list[dict[str, Any]] = []
    for location in locations[:10]:
        item: dict[str, Any] = {}
        for source_key, attr_key in (
            ("Name", "name"),
            ("Country", "country"),
            ("CountryId", "country_id"),
            ("LocationId", "location_id"),
        ):
            value = location.get(source_key)
            if value not in (None, ""):
                item[attr_key] = value
        search_type = weather_location_search_type(location)
        if search_type is not None:
            item["search_type"] = search_type
        if item:
            summary.append(item)
    return summary


def location_is_favorite(
    location: dict[str, Any],
    favorites: list[dict[str, Any]],
) -> bool:
    """Return whether the active weather location is a favorite."""
    location_id = location_identifier(location)
    if location_id is None:
        return False
    return any(location_identifier(favorite) == location_id for favorite in favorites)


def location_identifier(location: dict[str, Any]) -> str | None:
    """Return stable identifier for one DHE weather location."""
    location_id = location.get("LocationId")
    if location_id not in (None, ""):
        return str(location_id)
    country_id = location.get("CountryId")
    name = weather_location_name(location)
    if name and country_id not in (None, ""):
        return f"{country_id}:{name}"
    return name


def current_temperature(
    day: dict[str, Any],
    *,
    now: datetime | None = None,
) -> float | None:
    """Return best current temperature from a DHE day payload."""
    for key in ordered_period_keys("temp", now=now):
        value = number(day.get(key))
        if value is not None:
            return value

    tmax = number(day.get("tmax"))
    tmin = number(day.get("tmin"))
    if tmax is not None and tmin is not None:
        return round((tmax + tmin) / 2.0, 1)
    return tmax if tmax is not None else tmin


def current_condition_from_day(
    day: dict[str, Any],
    *,
    now: datetime | None = None,
) -> str | None:
    """Return best current HA weather condition from a DHE day payload."""
    current_period = current_weather_period(now)
    for key in ordered_period_keys("icon_id", include_day=True, now=now):
        condition = condition_from_icon_id(
            int_value(day.get(key)),
            precipitation=period_precipitation_probability(day, key),
        )
        if condition is not None:
            return condition

    precipitation = precipitation_probability(day, period=current_period)
    return condition_from_precipitation(
        precipitation if precipitation is not None else precipitation_probability(day)
    )


def daily_condition_from_day(day: dict[str, Any]) -> str | None:
    """Return best daily HA weather condition from a DHE day payload."""
    precipitation = precipitation_probability(day)
    for key in ("icon_id_day", "icon_id_midday", "icon_id_morning", "icon_id_evening"):
        condition = condition_from_icon_id(
            int_value(day.get(key)),
            precipitation=precipitation,
        )
        if condition is not None:
            return condition
    return condition_from_precipitation(precipitation)


def condition_from_icon_id(
    icon_id: int | None,
    *,
    precipitation: int | None,
) -> str | None:
    """Map DHE weather icon ids to HA weather conditions."""
    if icon_id is None:
        return None
    if icon_id == 7 and precipitation is not None and precipitation >= 70:
        return "pouring"
    return DHE_WEATHER_ICON_CONDITIONS.get(icon_id)


def condition_from_precipitation(precipitation: int | None) -> str | None:
    """Infer a condition from precipitation when no icon is available."""
    if precipitation is not None:
        if precipitation >= 70:
            return "pouring"
        if precipitation >= 40:
            return "partlycloudy"
    return None


def period_precipitation_probability(day: dict[str, Any], icon_key: str) -> int | None:
    """Return precipitation for the period represented by one icon key."""
    period = icon_key.removeprefix("icon_id_")
    if period not in WEATHER_DAY_PERIODS:
        return precipitation_probability(day)
    return precipitation_probability(day, period=period)


def precipitation_probability(
    day: dict[str, Any],
    *,
    period: str | None = None,
) -> int | None:
    """Return max precipitation probability from one DHE day payload."""
    keys = (
        (f"preci_{period}",)
        if period in WEATHER_DAY_PERIODS
        else ("preci_morning", "preci_midday", "preci_evening")
    )
    values = [number(day.get(key)) for key in keys]
    values = [value for value in values if value is not None]
    if not values:
        return None
    return int(round(max(values)))


def ordered_period_keys(
    prefix: str,
    *,
    include_day: bool = False,
    now: datetime | None = None,
) -> tuple[str, ...]:
    """Return period keys in display-priority order."""
    keys = [f"{prefix}_{current_weather_period(now)}"]
    if include_day:
        keys.append(f"{prefix}_day")
    for period in ("midday", "morning", "evening"):
        key = f"{prefix}_{period}"
        if key not in keys:
            keys.append(key)
    return tuple(keys)


def current_weather_period(now: datetime | None = None) -> str:
    """Return current weather day period."""
    hour = (now or datetime.now()).hour
    if hour < 12:
        return "morning"
    if hour < 18:
        return "midday"
    return "evening"


def number(value: Any) -> float | None:
    """Coerce a DHE weather value to float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def int_value(value: Any) -> int | None:
    """Coerce a DHE weather value to int."""
    current_number = number(value)
    return int(current_number) if current_number is not None else None
