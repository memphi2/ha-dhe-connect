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

from .client import DHEClient
from .const import DOMAIN

SUPPORT_FORECAST_DAILY = (
    WeatherEntityFeature.FORECAST_DAILY if WeatherEntityFeature is not None else 0
)


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
        if hasattr(self, "async_update_listeners"):
            self.hass.async_create_task(self.async_update_listeners())

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = available or self._have_weather_state
        self.async_write_ha_state()

    def _apply_weather_state(self, state: dict[str, Any]) -> None:
        if not state:
            return

        self._have_weather_state = True
        self._attr_available = True

        days = _forecast_source_days(state)
        today = days[0] if days else {}
        self._attr_condition = _condition_from_day(today)
        self._attr_native_temperature = _current_temperature(today)
        self._forecast = [
            forecast
            for day in days
            if (forecast := _forecast_from_day(day)) is not None
        ]
        self._attr_extra_state_attributes = _weather_attributes(state, today, self._forecast)


def _forecast_source_days(state: dict[str, Any]) -> list[dict[str, Any]]:
    days = state.get("complete_days")
    if isinstance(days, list) and days:
        return [day for day in days if isinstance(day, dict)]

    days = state.get("simple_days")
    if isinstance(days, list):
        return [day for day in days if isinstance(day, dict)]
    return []


def _forecast_from_day(day: dict[str, Any]) -> dict[str, Any] | None:
    date = day.get("date")
    if not date:
        return None

    forecast: dict[str, Any] = {"datetime": f"{date}T00:00:00+00:00"}
    condition = _condition_from_day(day)
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
    }
    location = state.get("location")
    if isinstance(location, dict):
        name = _location_name(location)
        if name:
            attributes["location_name"] = name
        for source_key, attr_key in (
            ("LocationId", "location_id"),
            ("Country", "country"),
            ("CountryId", "country_id"),
        ):
            value = location.get(source_key)
            if value not in (None, ""):
                attributes[attr_key] = value

    for key in (
        "icon_id_day",
        "icon_id_morning",
        "icon_id_midday",
        "icon_id_evening",
    ):
        icon_id = _int_value(today.get(key))
        if icon_id is not None:
            attributes[key] = icon_id
    precipitation = _precipitation_probability(today)
    if precipitation is not None:
        attributes["precipitation_probability"] = precipitation
    return attributes


def _location_name(location: dict[str, Any]) -> str | None:
    i18n_names = location.get("I18nNames")
    if isinstance(i18n_names, list):
        for item in i18n_names:
            if isinstance(item, dict) and item.get("Name"):
                return str(item["Name"])
    name = location.get("Name")
    return str(name) if name else None


def _current_temperature(day: dict[str, Any]) -> float | None:
    for key in ("temp_midday", "temp_morning", "temp_evening"):
        value = _number(day.get(key))
        if value is not None:
            return value

    tmax = _number(day.get("tmax"))
    tmin = _number(day.get("tmin"))
    if tmax is not None and tmin is not None:
        return round((tmax + tmin) / 2.0, 1)
    return tmax if tmax is not None else tmin


def _condition_from_day(day: dict[str, Any]) -> str | None:
    precipitation = _precipitation_probability(day)
    if precipitation is not None:
        if precipitation >= 70:
            return "rainy"
        if precipitation >= 40:
            return "partlycloudy"
    return None


def _precipitation_probability(day: dict[str, Any]) -> int | None:
    values = [
        _number(day.get(key))
        for key in ("preci_morning", "preci_midday", "preci_evening")
    ]
    values = [value for value in values if value is not None]
    if not values:
        return None
    return int(round(max(values)))


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_value(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None
