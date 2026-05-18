"""Radio and weather runtime state handlers for the DHE client."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .client_constants import APP_COMMAND_CONFIRMATION_TIMEOUT, WEATHER_CATALOG_TIMEOUT
from .client_diagnostics import (
    summarize_radio_value as _summarize_radio_value,
    summarize_weather_value as _summarize_weather_value,
)
from .client_mapping import (
    copy_dict_items as _copy_dict_items,
    copy_json_like_value as _copy_json_like_value,
    normalize_radio_stations_value as _normalize_radio_stations_value,
    normalize_radio_string_catalog as _normalize_radio_string_catalog,
    normalize_weather_favorites_value as _normalize_weather_favorites_value,
    normalize_weather_locations_value as _normalize_weather_locations_value,
    normalize_weather_value as _normalize_weather_value,
    radio_station_id as _radio_station_id,
)
from .client_types import DHEError, RadioCallback, WeatherCallback
from .client_value_helpers import (
    clamp as _clamp,
    raw_to_bool as _raw_to_bool,
    raw_to_float as _raw_to_float,
)
from .flow_helpers import (
    wait_for_generation_change as _wait_for_generation_change,
    wait_until as _wait_until,
)
from .protocol import (
    RADIO_CATALOG_FIELDS,
    RADIO_FAVORITES_SET_COMMAND,
    RADIO_GENRE_SET_COMMAND,
    RADIO_STATIONS_SET_COMMAND,
    WEATHER_COUNTRIES_SET_COMMAND,
    WEATHER_COUNTRY_SET_COMMAND,
    WEATHER_FAVORITES_SET_COMMAND,
    WEATHER_FORECAST_SET_COMMAND,
    WEATHER_LOCATION_SET_COMMAND,
)


class DHEClientRuntimeMediaMixin:
    """Track runtime radio and weather state plus command readback waiters."""

    if TYPE_CHECKING:
        _last_app_values: dict[str, Any]
        _last_radio_catalogs: dict[str, list[str]]
        _last_radio_favorites: list[dict[str, Any]]
        _last_radio_genres: list[str]
        _last_radio_state: dict[str, Any]
        _last_radio_stations: list[dict[str, Any]]
        _last_weather_countries: list[dict[str, Any]]
        _last_weather_state: dict[str, Any]
        _radio_callbacks: set[RadioCallback]
        _radio_catalog_generations: dict[str, int]
        _radio_favorites_generation: int
        _radio_genres_generation: int
        _radio_stations_generation: int
        _weather_callbacks: set[WeatherCallback]
        _weather_countries_generation: int
        _weather_favorites_generation: int
        _weather_search_generation: int

        def _notify_callbacks(
            self,
            callback_name: str,
            callbacks: set[Callable[..., None]],
            *args: Any,
        ) -> None: ...

    def _handle_radio_value(self, command: str, raw_value: Any) -> None:
        field = command.rsplit(":", 1)[-1]
        value: Any
        if field == "volume":
            try:
                value = int(_clamp(round(_raw_to_float(raw_value)), 0, 100))
            except (TypeError, ValueError):
                return
        elif field in {"play", "paired"}:
            try:
                value = _raw_to_bool(raw_value)
            except (TypeError, ValueError):
                return
        elif field == "station":
            if not isinstance(raw_value, dict):
                return
            value = dict(raw_value)
        elif field in RADIO_CATALOG_FIELDS and isinstance(raw_value, list):
            self._handle_radio_catalog_value(command, raw_value)
            return
        else:
            value = "" if raw_value is None else str(raw_value)

        self._last_app_values[command] = raw_value
        if self._last_radio_state.get(field) == value:
            return
        self._last_radio_state[field] = value
        self._notify_callbacks(
            "radio",
            self._radio_callbacks,
            self._copy_radio_state(),
        )

    def _handle_radio_catalog_value(self, command: str, raw_value: Any) -> None:
        self._last_app_values[command] = _summarize_radio_value(raw_value)
        field = command.rsplit(":", 1)[-1]
        if field not in RADIO_CATALOG_FIELDS:
            return

        catalog = _normalize_radio_string_catalog(raw_value)
        if catalog is None:
            return
        self._last_radio_catalogs[field] = catalog
        self._radio_catalog_generations[field] += 1
        if command == RADIO_GENRE_SET_COMMAND:
            self._last_radio_genres = catalog
            self._radio_genres_generation = self._radio_catalog_generations[field]

    def _handle_radio_stations_value(self, raw_value: Any) -> None:
        self._last_app_values[RADIO_STATIONS_SET_COMMAND] = _summarize_radio_value(
            raw_value
        )
        stations = _normalize_radio_stations_value(raw_value)
        if stations is None:
            return
        self._last_radio_stations = stations
        self._radio_stations_generation += 1

    def _handle_radio_favorites_value(self, raw_value: Any) -> None:
        self._last_app_values[RADIO_FAVORITES_SET_COMMAND] = _summarize_radio_value(
            raw_value
        )
        favorites = _normalize_radio_stations_value(raw_value)
        if favorites is None:
            return
        self._last_radio_favorites = favorites
        self._radio_favorites_generation += 1

        state = self._copy_radio_state()
        state["favorites"] = favorites
        if state != self._last_radio_state:
            self._last_radio_state = state
            self._notify_callbacks(
                "radio",
                self._radio_callbacks,
                self._copy_radio_state(),
            )

    def _copy_radio_state(self) -> dict[str, Any]:
        state = {
            key: _copy_json_like_value(value)
            for key, value in self._last_radio_state.items()
        }
        if self._radio_favorites_generation > 0 and "favorites" not in state:
            state["favorites"] = self._radio_favorites()
        return state

    def _radio_favorites(self) -> list[dict[str, Any]]:
        return _copy_dict_items(self._last_radio_favorites)

    def _handle_weather_value(self, command: str, raw_value: Any) -> None:
        self._last_app_values[command] = _summarize_weather_value(raw_value)

        if command == WEATHER_FAVORITES_SET_COMMAND:
            favorites = _normalize_weather_favorites_value(raw_value)
            if favorites is None:
                return
            state = self._copy_weather_state()
            state["favorites"] = favorites
            self._weather_favorites_generation += 1
            self._set_weather_state(state)
            return

        if command == WEATHER_COUNTRY_SET_COMMAND:
            state = self._copy_weather_state()
            try:
                state["country_id"] = int(_raw_to_float(raw_value))
            except (TypeError, ValueError):
                state.pop("country_id", None)
            self._set_weather_state(state)
            return

        if command == WEATHER_FORECAST_SET_COMMAND:
            results = _normalize_weather_locations_value(raw_value)
            if results is None:
                return
            state = self._copy_weather_state()
            state["forecast_results"] = results
            self._weather_search_generation += 1
            self._set_weather_state(state)
            return

        if command == WEATHER_COUNTRIES_SET_COMMAND:
            countries = _normalize_weather_locations_value(raw_value)
            if countries is None:
                return
            self._last_weather_countries = countries
            self._weather_countries_generation += 1
            return

        if command != WEATHER_LOCATION_SET_COMMAND:
            return

        if not isinstance(raw_value, dict):
            self._set_weather_state({})
            return
        state = _normalize_weather_value(raw_value)

        existing = self._copy_weather_state()
        for key in ("favorites", "country_id", "forecast_results"):
            if key in existing and key not in state:
                state[key] = existing[key]
        self._set_weather_state(state)

    def _set_weather_state(self, state: dict[str, Any]) -> None:
        if self._last_weather_state == state:
            return
        self._last_weather_state = state
        self._notify_callbacks(
            "weather",
            self._weather_callbacks,
            self._copy_weather_state(),
        )

    def _copy_weather_state(self) -> dict[str, Any]:
        return {
            key: _copy_json_like_value(value)
            for key, value in self._last_weather_state.items()
        }

    def _weather_favorites(self) -> list[dict[str, Any]]:
        favorites = self._last_weather_state.get("favorites")
        return _copy_dict_items(favorites)

    async def _wait_for_radio_stations(
        self,
        previous_generation: int,
    ) -> list[dict[str, Any]]:
        if await _wait_for_generation_change(
            previous_generation,
            lambda: self._radio_stations_generation,
            timeout_seconds=APP_COMMAND_CONFIRMATION_TIMEOUT,
        ):
            return _copy_dict_items(self._last_radio_stations)
        raise DHEError("radio station search timed out")

    async def _wait_for_radio_favorites(
        self,
        previous_generation: int,
    ) -> list[dict[str, Any]]:
        if await _wait_for_generation_change(
            previous_generation,
            lambda: self._radio_favorites_generation,
            timeout_seconds=APP_COMMAND_CONFIRMATION_TIMEOUT,
        ):
            return self._radio_favorites()
        raise DHEError("radio favorites timed out")

    async def _wait_for_radio_catalog(
        self,
        attribute: str,
        previous_generation: int,
    ) -> list[str]:
        requested_attribute = str(attribute).strip().lower()
        if await _wait_for_generation_change(
            previous_generation,
            lambda: self._radio_catalog_generations.get(requested_attribute, 0),
            timeout_seconds=WEATHER_CATALOG_TIMEOUT,
        ):
            return list(self._last_radio_catalogs.get(requested_attribute, []))
        catalog = self._last_radio_catalogs.get(requested_attribute, [])
        if catalog:
            return list(catalog)
        raise DHEError(f"radio {requested_attribute} catalog timed out")

    async def _wait_for_radio_genres(self, previous_generation: int) -> list[str]:
        return await self._wait_for_radio_catalog("genre", previous_generation)

    async def _wait_for_radio_station(self, station_id: int) -> None:
        if await _wait_until(
            lambda: (
                isinstance(self._last_radio_state.get("station"), dict)
                and _radio_station_id(self._last_radio_state["station"]) == station_id
            ),
            timeout_seconds=APP_COMMAND_CONFIRMATION_TIMEOUT,
        ):
            return
        raise DHEError("radio station selection timed out")

    async def _wait_for_weather_search_results(
        self,
        previous_generation: int,
    ) -> list[dict[str, Any]]:
        if await _wait_for_generation_change(
            previous_generation,
            lambda: self._weather_search_generation,
            timeout_seconds=APP_COMMAND_CONFIRMATION_TIMEOUT,
        ):
            results = self._last_weather_state.get("forecast_results")
            return _copy_dict_items(results)
        raise DHEError("weather location search timed out")

    async def _wait_for_weather_countries(
        self,
        previous_generation: int,
    ) -> list[dict[str, Any]]:
        if await _wait_for_generation_change(
            previous_generation,
            lambda: self._weather_countries_generation,
            timeout_seconds=WEATHER_CATALOG_TIMEOUT,
        ):
            return _copy_dict_items(self._last_weather_countries)
        if self._last_weather_countries:
            return _copy_dict_items(self._last_weather_countries)
        raise DHEError("weather country catalog timed out")

    async def _wait_for_weather_favorites(
        self,
        previous_generation: int,
    ) -> list[dict[str, Any]]:
        if await _wait_for_generation_change(
            previous_generation,
            lambda: self._weather_favorites_generation,
            timeout_seconds=APP_COMMAND_CONFIRMATION_TIMEOUT,
        ):
            return self._weather_favorites()
        raise DHEError("weather favorites timed out")

    async def _wait_for_weather_location(
        self,
        location_id: str,
    ) -> None:
        if await _wait_until(
            lambda: (
                isinstance(self._last_weather_state.get("location"), dict)
                and str(self._last_weather_state["location"].get("LocationId", ""))
                == location_id
            ),
            timeout_seconds=APP_COMMAND_CONFIRMATION_TIMEOUT,
        ):
            return
        raise DHEError("weather location selection timed out")
