"""Weather platform for DHE Connect."""

from __future__ import annotations

import inspect
from importlib import import_module
from typing import TYPE_CHECKING, Any, cast

from homeassistant.components.weather import WeatherEntity

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .async_helpers import create_background_task
from .client import DHEClient
from .entity_helpers import StiebelDHEEntityMixin
from .entity_state_helpers import connected_and_ready, filtered_state_attributes
from . import weather_mapping as weather_model
from .runtime_helpers import get_runtime_data

if TYPE_CHECKING:
    from homeassistant.components.weather import Forecast

PARALLEL_UPDATES = 0


def _weather_feature_value(name: str, fallback: int = 0) -> Any:
    """Return a weather feature value across HA module layouts."""
    for module_name in (
        "homeassistant.components.weather",
        "homeassistant.components.weather.const",
    ):
        try:
            feature_cls = getattr(import_module(module_name), "WeatherEntityFeature")
        except (AttributeError, ImportError):
            continue
        return getattr(feature_cls, name, fallback)
    return fallback


SUPPORT_FORECAST_DAILY = _weather_feature_value("FORECAST_DAILY")


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
    _unrecorded_attributes = frozenset({
        "favorite_locations",
        "forecast_results",
        "int_names",
    })

    def __init__(self, entry_id: str, name: str, client: DHEClient) -> None:
        """Initialize the DHE weather entity."""
        self._init_dhe_entity(
            entry_id=entry_id,
            key="weather",
            name=name,
            client=client,
        )
        self._attr_available = False
        self._attr_condition: str | None = None
        self._attr_name: str | None = None
        self._attr_extra_state_attributes = {"weather_path": "ste.app.weather"}
        self._attr_native_temperature: float | None = None
        self._client_available = client.available
        self._forecast: list[Forecast] = []
        self._have_weather_state = False
        self._last_written_weather_signature: tuple[Any, ...] | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to DHE weather updates."""
        self.async_on_remove(
            self._client.add_weather_callback(self._handle_weather_update)
        )
        self.async_on_remove(
            self._client.add_availability_callback(self._handle_availability_update)
        )
        self._apply_weather_state(self._client.last_weather_state)

    async def async_forecast_daily(self) -> list[Forecast] | None:
        """Return daily weather forecast."""
        return list(self._forecast) if self._forecast else None

    @callback
    def _handle_weather_update(self, state: dict[str, Any]) -> None:
        """Handle weather updates from the persistent client."""
        self._apply_weather_state(state)
        if self._write_weather_state():
            self._schedule_forecast_listener_update()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._client_available = available
        self._attr_available = connected_and_ready(
            self._client_available,
            self._have_weather_state,
        )
        self._write_weather_state()

    def _write_weather_state(self, *, force: bool = False) -> bool:
        """Write weather state only when recorder-visible state changed."""
        signature = self._weather_write_signature()
        if not force and signature == self._last_written_weather_signature:
            return False
        self._last_written_weather_signature = signature
        self.async_write_ha_state()
        return True

    def _weather_write_signature(self) -> tuple[Any, ...]:
        """Return stable weather fields that should trigger a state write."""
        return (
            self._attr_available,
            self._attr_condition,
            self._attr_native_temperature,
            self._attr_name,
            list(self._forecast),
            self._recorded_weather_attributes(),
        )

    def _recorded_weather_attributes(self) -> dict[str, Any]:
        """Return weather attributes that should participate in recorder writes."""
        return filtered_state_attributes(
            self._attr_extra_state_attributes,
            self._unrecorded_attributes,
        )

    def _schedule_forecast_listener_update(self) -> None:
        update_listeners = getattr(self, "async_update_listeners", None)
        if update_listeners is None:
            return
        try:
            result = update_listeners(("daily",))
        except TypeError:  # pragma: no cover - older HA compatibility
            result = update_listeners()
        if inspect.isawaitable(result):
            create_background_task(
                self.hass,
                result,
                "stiebel_dhe_connect_weather_listener_update",
            )

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
            cast("Forecast", forecast)
            for day in days
            if (
                forecast := weather_model.forecast_from_day(
                    day,
                    time_zone=now.tzinfo,
                )
            )
            is not None
        ]
        self._attr_name = weather_model.weather_entity_name(state)
        self._attr_extra_state_attributes = weather_model.weather_attributes(
            state,
            today,
            [dict(forecast) for forecast in self._forecast],
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
