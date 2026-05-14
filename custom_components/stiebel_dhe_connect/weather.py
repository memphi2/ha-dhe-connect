"""Weather platform for Stiebel DHE Connect."""

from __future__ import annotations

import inspect
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
from .entity_helpers import StiebelDHEEntityMixin
from .entity_state_helpers import connected_and_ready
from . import weather_mapping as weather_model
from .runtime_helpers import get_runtime_data

SUPPORT_FORECAST_DAILY = (
    WeatherEntityFeature.FORECAST_DAILY if WeatherEntityFeature is not None else 0
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DHE weather entities from a config entry."""
    runtime = get_runtime_data(hass, entry)
    async_add_entities([
        StiebelDHEWeather(
            entry_id=entry.entry_id,
            name=runtime.name,
            client=runtime.client,
        )
    ])


class StiebelDHEWeather(StiebelDHEEntityMixin, WeatherEntity):
    """Weather forecast provided by the DHE app protocol."""

    _attr_has_entity_name = True
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_should_poll = False
    _attr_supported_features = SUPPORT_FORECAST_DAILY
    _attr_translation_key = "weather"

    def __init__(self, entry_id: str, name: str, client: DHEClient) -> None:
        """Initialize the DHE weather entity."""
        self._init_dhe_entity(
            entry_id=entry_id,
            key="weather",
            name=name,
            client=client,
        )
        self._attr_available = False
        self._attr_condition = None
        self._attr_name = None
        self._attr_extra_state_attributes = {"weather_path": "ste.app.weather"}
        self._attr_native_temperature = None
        self._client_available = client.available
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
        self._client_available = available
        self._attr_available = connected_and_ready(
            self._client_available,
            self._have_weather_state,
        )
        self.async_write_ha_state()

    def _schedule_forecast_listener_update(self) -> None:
        update_listeners = getattr(self, "async_update_listeners", None)
        if update_listeners is None:
            return
        try:
            result = update_listeners(("daily",))
        except TypeError:  # pragma: no cover - older HA compatibility
            result = update_listeners()
        if inspect.iscoroutine(result):
            self.hass.async_create_task(result)

    def _apply_weather_state(self, state: dict[str, Any]) -> None:
        if not state:
            self._reset_weather_state()
            return

        days = weather_model.forecast_source_days(state)
        location = state.get("location")
        has_location = isinstance(location, dict) and bool(location)
        if not days and not has_location:
            self._reset_weather_state()
            return

        today = days[0] if days else {}
        now = dt_util.now()
        self._attr_condition = weather_model.current_condition_from_day(today, now=now)
        self._attr_native_temperature = weather_model.current_temperature(today, now=now)
        self._forecast = [
            forecast
            for day in days
            if (forecast := weather_model.forecast_from_day(day)) is not None
        ]
        self._attr_name = weather_model.weather_entity_name(state)
        self._attr_extra_state_attributes = weather_model.weather_attributes(
            state,
            today,
            self._forecast,
            now=now,
        )
        self._have_weather_state = (
            has_location
            or self._attr_condition is not None
            or self._attr_native_temperature is not None
            or bool(self._forecast)
        )
        self._attr_available = connected_and_ready(
            self._client_available,
            self._have_weather_state,
        )

    def _reset_weather_state(self) -> None:
        """Reset entity state to unavailable."""
        self._have_weather_state = False
        self._attr_available = False
        self._attr_condition = None
        self._attr_name = None
        self._attr_native_temperature = None
        self._forecast = []
        self._attr_extra_state_attributes = {"weather_path": "ste.app.weather"}
