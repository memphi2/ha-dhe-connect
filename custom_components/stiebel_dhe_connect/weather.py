"""Weather platform for Stiebel DHE Connect."""

from __future__ import annotations

from typing import Any

from homeassistant.components.weather import WeatherEntity

try:
    from homeassistant.components.weather import WeatherEntityFeature
except ImportError:  # pragma: no cover - compatibility with older HA versions
    WeatherEntityFeature = None

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .client import DHEClient
from .const import DOMAIN

SUPPORT_FORECAST_DAILY = (
    WeatherEntityFeature.FORECAST_DAILY if WeatherEntityFeature is not None else 0
)

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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DHE weather entities from a config entry."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        StiebelDHEWeather(
            entry_id=entry.entry_id,
            name=runtime.name,
            client=runtime.client,
        )
    ])


class StiebelDHEWeather(WeatherEntity):
    """Weather forecast provided by the DHE app protocol."""

    _attr_has_entity_name = True
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_should_poll = False
    _attr_supported_features = SUPPORT_FORECAST_DAILY
    _attr_translation_key = "weather"

    def __init__(self, entry_id: str, name: str, client: DHEClient) -> None:
        """Initialize the DHE weather entity."""
        self._attr_unique_id = f"stiebel_dhe_connect_{entry_id}_weather"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, client.host)},
            "manufacturer": "STIEBEL ELTRON",
            "model": "DHE Connect",
            "name": name,
        }
        self._attr_available = False
        self._attr_condition = None
        self._attr_name = None
        self._attr_extra_state_attributes = {"weather_path": "ste.app.weather"}
        self._attr_native_temperature = None
        self._client = client
        self._forecast: list[dict[str, Any]] = []
        self._have_weather_state = False

    async def async_added_to_hass(self) -> None:
        """Subscribe to DHE weather updates."""
        self.async_on_remove(
            self._client.add_weather_callback(self._handle_weather_update)
        )
        self.async_on_remove(
            self._client.add_availability_callback(self._handle_availability_update)
        )
        self._apply_weather_state(self._client.last_weather_state)

    async def async_forecast_daily(self) -> list[dict[str, Any]] | None:
        """Return daily weather forecast."""
        return list(self._forecast) if self._forecast else None

    @callback
    def _handle_weather_update(self, state: dict[str, Any]) -> None:
        """Handle weather updates from the persistent client."""
        self._apply_weather_state(state)
        self.async_write_ha_state()
        self._schedule_forecast_listener_update()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = available or self._have_weather_state
        self.async_write_ha_state()

    def _schedule_forecast_listener_update(self) -> None:
        update_listeners = getattr(self, "async_update_listeners", None)
        if update_listeners is None:
            return
        try:
            task = update_listeners(("daily",))
        except TypeError:  # pragma: no cover - older HA compatibility
            task = update_listeners()
        self.hass.async_create_task(task)

    def _apply_weather_state(self, state: dict[str, Any]) -> None:
        if not state:
            self._have_weather_state = False
            self._attr_available = False
            self._attr_condition = None
            self._attr_name = None
            self._attr_native_temperature = None
            self._forecast = []
            self._attr_extra_state_attributes = {"weather_path": "ste.app.weather"}
            return

        days = _forecast_source_days(state)
        if not days and not isinstance(state.get("location"), dict):
            self._have_weather_state = False
            self._attr_available = False
            self._attr_condition = None
            self._attr_name = None
            self._attr_native_temperature = None
            self._forecast = []
            self._attr_extra_state_attributes = {"weather_path": "ste.app.weather"}
            return

        self._have_weather_state = True
        self._attr_available = True

        today = days[0] if days else {}
        self._attr_condition = _current_condition_from_day(today)
        self._attr_native_temperature = _current_temperature(today)
        self._forecast = [
            forecast
            for day in days
            if (forecast := _forecast_from_day(day)) is not None
        ]
        self._attr_name = _weather_entity_name(state)
        self._attr_extra_state_attributes = _weather_attributes(state, today, self._forecast)


def _forecast_source_days(state: dict[str, Any]) -> list[dict[str, Any]]:
    days = state.get("complete_days")
    if isinstance(days, list) and days:
        return _deduplicate_forecast_days([day for day in days if isinstance(day, dict)])

    days = state.get("simple_days")
    if isinstance(days, list):
        return _deduplicate_forecast_days([day for day in days if isinstance(day, dict)])
    return []


def _deduplicate_forecast_days(days: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def _forecast_from_day(day: dict[str, Any]) -> dict[str, Any] | None:
    date = day.get("date")
    if not date:
        return None

    forecast: dict[str, Any] = {"datetime": f"{date}T00:00:00+00:00"}
    condition = _daily_condition_from_day(day)
    tmax = _number(day.get("tmax"))
    tmin = _number(day.get("tmin"))
    precipitation = _precipitation_probability(day)
    if condition is not None:
        forecast["condition"] = condition
    if tmax is not None:
        forecast["native_temperature"] = tmax
    if tmin is not None:
        forecast["native_templow"] = tmin
    if precipitation is not None:
        forecast["precipitation_probability"] = precipitation
    return forecast


def _weather_attributes(
    state: dict[str, Any],
    today: dict[str, Any],
    forecast: list[dict[str, Any]],
) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "weather_path": "ste.app.weather",
        "forecast_days": len(forecast),
        "current_period": _current_weather_period(),
    }
    location = state.get("location")
    if isinstance(location, dict):
        name = weather_location_name(location)
        location_attributes = weather_location_attributes(location)
        if name:
            attributes["location_name"] = name
            attributes["city"] = name
        display_location = _weather_location_display(
            name,
            location_attributes.get("country"),
        )
        if display_location:
            attributes["location"] = display_location
            attributes["location_label"] = display_location
        attributes.update(location_attributes)
        favorites = _weather_favorites(state)
        if favorites:
            attributes["favorite_count"] = len(favorites)
            attributes["is_favorite"] = _location_is_favorite(location, favorites)
            attributes["favorite_locations"] = _weather_locations_summary(favorites)
        forecast_results = _weather_forecast_results(state)
        if forecast_results:
            attributes["forecast_result_count"] = len(forecast_results)
            attributes["forecast_results"] = _weather_locations_summary(forecast_results)

    for key in (
        "icon_id_day",
        "icon_id_morning",
        "icon_id_midday",
        "icon_id_evening",
    ):
        icon_id = _int_value(today.get(key))
        if icon_id is not None:
            attributes[key] = icon_id
            description = DHE_WEATHER_ICON_DESCRIPTIONS.get(icon_id)
            if description is not None:
                attributes[key.replace("icon_id_", "icon_")] = description
            precipitation = _period_precipitation_probability(today, key)
            condition = _condition_from_icon_id(
                icon_id,
                precipitation=precipitation,
            )
            if condition is not None:
                attributes[key.replace("icon_id_", "condition_")] = condition
    precipitation = _precipitation_probability(today)
    if precipitation is not None:
        attributes["precipitation_probability"] = precipitation
    country_id = _int_value(state.get("country_id"))
    if country_id is not None:
        attributes["selected_country_id"] = country_id
    return attributes


def _weather_entity_name(state: dict[str, Any]) -> str | None:
    """Use city/country as weather entity name when available."""
    location = state.get("location")
    if not isinstance(location, dict):
        return None
    name = weather_location_name(location)
    country = location.get("Country")
    return _weather_location_display(name, country)


def _weather_location_display(name: str | None, country: Any) -> str | None:
    country_text = str(country).strip() if country not in (None, "") else ""
    name_text = str(name).strip() if name else ""
    if country_text and name_text:
        return f"{name_text}, {country_text}"
    return name_text or country_text or None


def weather_location_name(location: dict[str, Any]) -> str | None:
    """Return the best display name from a DHE weather location payload."""
    for item in _weather_location_name_entries(location):
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

    search_type = _weather_location_search_type(location)
    if search_type is not None:
        attributes["search_type"] = search_type

    names = _weather_location_name_entries(location)
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


def _weather_location_name_entries(location: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("IntNames", "I18nNames"):
        names = location.get(key)
        if isinstance(names, list):
            entries = [item for item in names if isinstance(item, dict)]
            if entries:
                return entries
    return []


def _weather_location_search_type(location: dict[str, Any]) -> int | None:
    search_type = _int_value(location.get("SearchType"))
    if search_type is not None:
        return search_type
    for item in _weather_location_name_entries(location):
        search_type = _int_value(item.get("SearchType"))
        if search_type is not None:
            return search_type
    return None


def _weather_favorites(state: dict[str, Any]) -> list[dict[str, Any]]:
    favorites = state.get("favorites")
    if not isinstance(favorites, list):
        return []
    return [item for item in favorites if isinstance(item, dict)]


def _weather_forecast_results(state: dict[str, Any]) -> list[dict[str, Any]]:
    results = state.get("forecast_results")
    if not isinstance(results, list):
        return []
    return [item for item in results if isinstance(item, dict)]


def _weather_locations_summary(locations: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
        search_type = _weather_location_search_type(location)
        if search_type is not None:
            item["search_type"] = search_type
        if item:
            summary.append(item)
    return summary


def _location_is_favorite(
    location: dict[str, Any],
    favorites: list[dict[str, Any]],
) -> bool:
    location_id = _location_identifier(location)
    if location_id is None:
        return False
    return any(_location_identifier(favorite) == location_id for favorite in favorites)


def _location_identifier(location: dict[str, Any]) -> str | None:
    location_id = location.get("LocationId")
    if location_id not in (None, ""):
        return str(location_id)
    country_id = location.get("CountryId")
    name = weather_location_name(location)
    if name and country_id not in (None, ""):
        return f"{country_id}:{name}"
    return name


def _current_temperature(day: dict[str, Any]) -> float | None:
    for key in _ordered_period_keys("temp"):
        value = _number(day.get(key))
        if value is not None:
            return value

    tmax = _number(day.get("tmax"))
    tmin = _number(day.get("tmin"))
    if tmax is not None and tmin is not None:
        return round((tmax + tmin) / 2.0, 1)
    return tmax if tmax is not None else tmin


def _current_condition_from_day(day: dict[str, Any]) -> str | None:
    for key in _ordered_period_keys("icon_id", include_day=True):
        condition = _condition_from_icon_id(
            _int_value(day.get(key)),
            precipitation=_period_precipitation_probability(day, key),
        )
        if condition is not None:
            return condition

    precipitation = _precipitation_probability(day, period=_current_weather_period())
    return _condition_from_precipitation(
        precipitation if precipitation is not None else _precipitation_probability(day)
    )


def _daily_condition_from_day(day: dict[str, Any]) -> str | None:
    precipitation = _precipitation_probability(day)
    for key in ("icon_id_day", "icon_id_midday", "icon_id_morning", "icon_id_evening"):
        condition = _condition_from_icon_id(
            _int_value(day.get(key)),
            precipitation=precipitation,
        )
        if condition is not None:
            return condition
    return _condition_from_precipitation(precipitation)


def _condition_from_icon_id(
    icon_id: int | None,
    *,
    precipitation: int | None,
) -> str | None:
    if icon_id is None:
        return None
    if icon_id == 7 and precipitation is not None and precipitation >= 70:
        return "pouring"
    return DHE_WEATHER_ICON_CONDITIONS.get(icon_id)


def _condition_from_precipitation(precipitation: int | None) -> str | None:
    if precipitation is not None:
        if precipitation >= 70:
            return "pouring"
        if precipitation >= 40:
            return "partlycloudy"
    return None


def _period_precipitation_probability(day: dict[str, Any], icon_key: str) -> int | None:
    period = icon_key.removeprefix("icon_id_")
    if period not in WEATHER_DAY_PERIODS:
        return _precipitation_probability(day)
    return _precipitation_probability(day, period=period)


def _precipitation_probability(
    day: dict[str, Any],
    *,
    period: str | None = None,
) -> int | None:
    keys = (
        (f"preci_{period}",)
        if period in WEATHER_DAY_PERIODS
        else ("preci_morning", "preci_midday", "preci_evening")
    )
    values = [_number(day.get(key)) for key in keys]
    values = [value for value in values if value is not None]
    if not values:
        return None
    return int(round(max(values)))


def _ordered_period_keys(prefix: str, *, include_day: bool = False) -> tuple[str, ...]:
    keys = [f"{prefix}_{_current_weather_period()}"]
    if include_day:
        keys.append(f"{prefix}_day")
    for period in ("midday", "morning", "evening"):
        key = f"{prefix}_{period}"
        if key not in keys:
            keys.append(key)
    return tuple(keys)


def _current_weather_period() -> str:
    hour = dt_util.now().hour
    if hour < 12:
        return "morning"
    if hour < 18:
        return "midday"
    return "evening"


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_value(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None
