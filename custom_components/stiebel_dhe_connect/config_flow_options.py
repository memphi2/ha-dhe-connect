"""Options flow for DHE Connect."""

from __future__ import annotations

from typing import Any, Protocol, cast

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT

from . import config_flow as _config_flow
from .client_types import DHEError
from .config_entry_helpers import merged_entry_data
from .config_flow_mapping import (
    filter_radio_results_by_text as _filter_radio_results_by_text,
    radio_catalog_options as _radio_catalog_options,
    radio_result_options as _radio_result_options,
    weather_country_options as _weather_country_options,
    weather_result_options as _weather_result_options,
)
from .config_flow_schemas import (
    ATTR_CO2_EMISSION,
    ATTR_COUNTRY_ID,
    ATTR_ELECTRICITY_PRICE,
    ATTR_RADIO_FILTER_TEXT,
    ATTR_RADIO_SEARCH_TYPE,
    ATTR_RADIO_SELECTION,
    ATTR_RESULT,
    ATTR_WATER_PRICE,
    MAX_RADIO_RESULT_OPTIONS,
    MAX_WEATHER_RESULT_OPTIONS,
    RADIO_CATALOG_SEARCH_TYPES,
    RADIO_FILTER_SEARCH_TYPES,
    RADIO_SEARCH_TYPES,
    device_settings_defaults as _device_settings_defaults,
    device_settings_schema as _device_settings_schema,
    optional_float as _optional_float,
    radio_catalog_schema as _radio_catalog_schema,
    radio_search_type_schema as _radio_search_type_schema,
    schema as _schema,
    weather_search_schema as _weather_search_schema,
)
from .connection_helpers import target_changed
from .const import DEFAULT_PORT
from .payload_types import (
    RadioStationPayload,
    WeatherCountryPayload,
    WeatherLocationPayload,
)
from .protocol import (
    CO2_EMISSION_MAX,
    ELECTRICITY_PRICE_MAX,
    WATER_PRICE_MAX,
)


class _OptionsFlowClient(Protocol):
    """Client surface used by the options flow."""

    async def set_electricity_price(self, euros_per_kwh: float) -> float: ...

    async def set_water_price(self, euros_per_m3: float) -> float: ...

    async def set_co2_emission(self, kg_per_kwh: float) -> float: ...

    async def list_weather_countries(self) -> list[WeatherCountryPayload]: ...

    async def search_weather_locations(
        self,
        name: str,
        country_id: int | float | str,
    ) -> list[WeatherLocationPayload]: ...

    async def list_weather_favorites(self) -> list[WeatherLocationPayload]: ...

    async def add_weather_favorite(self, location: WeatherLocationPayload) -> bool: ...

    async def remove_weather_favorite(self, location: WeatherLocationPayload) -> bool: ...

    async def list_radio_catalog(self, attribute: str) -> list[str]: ...

    async def search_radio_stations(
        self,
        attribute: str,
        value: str,
        *,
        search_text: str | None = None,
    ) -> list[RadioStationPayload]: ...

    async def list_radio_favorites(self) -> list[RadioStationPayload]: ...

    async def add_radio_favorite(
        self,
        station: RadioStationPayload | int | str,
        *,
        select: bool = True,
    ) -> bool: ...

    async def remove_radio_favorite(
        self,
        station: RadioStationPayload | int | str,
    ) -> bool:
        ...


class StiebelDHEConnectOptionsFlow(config_entries.OptionsFlow):
    """Options flow for DHE Connect."""

    def __init__(self) -> None:
        self._radio_catalogs: dict[str, list[str]] = {}
        self._radio_favorites: list[RadioStationPayload] = []
        self._radio_results: list[RadioStationPayload] = []
        self._radio_search_type = "text"
        self._weather_countries: list[WeatherCountryPayload] = []
        self._weather_favorites: list[WeatherLocationPayload] = []
        self._weather_results: list[WeatherLocationPayload] = []
        self._menu_options: list[str] = [
            "connection",
            "device_settings",
            "weather_favorite",
            "remove_weather_favorite",
            "radio_favorite",
            "remove_radio_favorite",
        ]

    def _finish_options(self) -> config_entries.ConfigFlowResult:
        """Return success result without changing options payload."""
        return self.async_create_entry(
            title="",
            data=dict(self.config_entry.options),
        )

    def _client_or_mark_not_loaded(
        self,
        errors: dict[str, str],
    ) -> _OptionsFlowClient | None:
        """Return runtime client or mark the step as not loaded."""
        client = self._client()
        if client is None:
            errors["base"] = "not_loaded"
        return client

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Show the options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=self._menu_options,
        )

    async def async_step_connection(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage connection options."""
        current = merged_entry_data(self.config_entry)
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                data = _config_flow._connection_data_from_user_input(user_input)
            except ValueError as err:
                _config_flow._apply_validation_error(errors, err)
            else:
                host = data[CONF_HOST]
                port = data[CONF_PORT]

                if _config_flow._is_target_used_by_other_entry(
                    self.hass,
                    host,
                    port,
                    exclude_entry_id=self.config_entry.entry_id,
                ):
                    errors["base"] = "already_configured"
                else:
                    changed = target_changed(
                        current,
                        host,
                        port,
                        default_port=DEFAULT_PORT,
                    )
                    if changed and not await _config_flow._can_connect(self.hass, host, port):
                        errors["base"] = "cannot_connect"
                        return self.async_show_form(
                            step_id="connection",
                            data_schema=_schema(self.hass, data),
                            errors=errors,
                        )

                    if changed:
                        await _config_flow._async_preserve_token_for_retarget(
                            self.hass,
                            self.config_entry,
                            data,
                        )
                    return self.async_create_entry(
                        title="",
                        data=_config_flow._connection_options_for_entry(self.config_entry, data),
                    )

        return self.async_show_form(
            step_id="connection",
            data_schema=_schema(self.hass, current),
            errors=errors,
        )

    async def async_step_device_settings(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage DHE cost and emission settings."""
        errors: dict[str, str] = {}
        client = self._client_or_mark_not_loaded(errors)

        defaults = _device_settings_defaults(client) if client is not None else {}
        if user_input is not None and not errors and client is not None:
            try:
                electricity_price = _optional_float(
                    user_input.get(ATTR_ELECTRICITY_PRICE),
                    0.0,
                    ELECTRICITY_PRICE_MAX,
                )
                water_price = _optional_float(
                    user_input.get(ATTR_WATER_PRICE),
                    0.0,
                    WATER_PRICE_MAX,
                )
                co2_emission = _optional_float(
                    user_input.get(ATTR_CO2_EMISSION),
                    0.0,
                    CO2_EMISSION_MAX,
                )

                if electricity_price is not None:
                    await client.set_electricity_price(electricity_price)
                if water_price is not None:
                    await client.set_water_price(water_price)
                if co2_emission is not None:
                    await client.set_co2_emission(co2_emission)
            except (TypeError, ValueError):
                errors["base"] = "invalid_device_setting"
            except DHEError:
                errors["base"] = "device_settings_failed"
            else:
                return self._finish_options()

        return self.async_show_form(
            step_id="device_settings",
            data_schema=_device_settings_schema(self.hass, user_input or defaults),
            errors=errors,
        )

    async def async_step_weather_favorite(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Search DHE weather locations to add a favorite."""
        errors: dict[str, str] = {}
        client = self._client_or_mark_not_loaded(errors)
        if client is not None and not self._weather_countries:
            try:
                self._weather_countries = await client.list_weather_countries()
            except DHEError:
                errors["base"] = "cannot_connect"

        country_options = _weather_country_options(self._weather_countries)
        defaults = user_input or {}

        if user_input is not None and not errors and client is not None:
            search_name = str(user_input.get(CONF_NAME, "")).strip()
            if not search_name:
                errors[CONF_NAME] = "required"
            else:
                try:
                    country_id = int(user_input[ATTR_COUNTRY_ID])
                    self._weather_results = await client.search_weather_locations(
                        search_name,
                        country_id,
                    )
                except (TypeError, ValueError):
                    errors[ATTR_COUNTRY_ID] = "invalid_country"
                except DHEError:
                    errors["base"] = "search_failed"
                else:
                    if not self._weather_results:
                        errors["base"] = "no_results"
                    else:
                        return await self.async_step_weather_favorite_result()

        if not country_options and not errors:
            errors["base"] = "no_countries"

        return self.async_show_form(
            step_id="weather_favorite",
            data_schema=_weather_search_schema(country_options, defaults),
            errors=errors,
        )

    async def async_step_weather_favorite_result(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Select one weather search result and save it as favorite."""
        errors: dict[str, str] = {}
        client = self._client_or_mark_not_loaded(errors)
        result_options = _weather_result_options(
            self._weather_results,
            max_options=MAX_WEATHER_RESULT_OPTIONS,
        )

        if not result_options and "base" not in errors:
            errors["base"] = "no_results"

        if user_input is not None and not errors and client is not None:
            try:
                selected = int(user_input[ATTR_RESULT])
                location = self._weather_results[selected]
                await client.add_weather_favorite(location)
            except (IndexError, TypeError, ValueError):
                errors[ATTR_RESULT] = "invalid_result"
            except DHEError:
                errors["base"] = "favorite_failed"
            else:
                return self._finish_options()

        return self.async_show_form(
            step_id="weather_favorite_result",
            data_schema=vol.Schema({vol.Required(ATTR_RESULT): vol.In(result_options)}),
            errors=errors,
        )

    async def async_step_remove_weather_favorite(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Remove a DHE weather favorite."""
        errors: dict[str, str] = {}
        client = self._client_or_mark_not_loaded(errors)
        if client is not None and user_input is None:
            try:
                self._weather_favorites = await client.list_weather_favorites()
            except DHEError:
                errors["base"] = "cannot_connect"

        favorite_options = _weather_result_options(
            self._weather_favorites,
            max_options=MAX_WEATHER_RESULT_OPTIONS,
        )
        if not favorite_options and not errors:
            errors["base"] = "no_favorites"

        if user_input is not None and not errors and client is not None:
            try:
                selected = int(user_input[ATTR_RESULT])
                location = self._weather_favorites[selected]
                await client.remove_weather_favorite(location)
            except (IndexError, TypeError, ValueError):
                errors[ATTR_RESULT] = "invalid_result"
            except DHEError:
                errors["base"] = "remove_favorite_failed"
            else:
                return self._finish_options()

        return self.async_show_form(
            step_id="remove_weather_favorite",
            data_schema=vol.Schema({vol.Required(ATTR_RESULT): vol.In(favorite_options)}),
            errors=errors,
        )

    async def async_step_radio_favorite(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Select how DHE radio stations should be searched."""
        errors: dict[str, str] = {}
        defaults = user_input or {}

        if user_input is not None:
            search_type = str(user_input.get(ATTR_RADIO_SEARCH_TYPE, "")).strip()
            if search_type not in RADIO_SEARCH_TYPES:
                errors[ATTR_RADIO_SEARCH_TYPE] = "invalid_radio_search_type"
            else:
                self._radio_search_type = search_type
                self._radio_results = []
                return await self.async_step_radio_favorite_catalog()

        return self.async_show_form(
            step_id="radio_favorite",
            data_schema=_radio_search_type_schema(self.hass, defaults),
            errors=errors,
        )

    def _effective_radio_search_type(self) -> str:
        """Return the currently selected radio search type."""
        if self._radio_search_type in RADIO_SEARCH_TYPES:
            return self._radio_search_type
        return "text"

    async def _ensure_radio_catalog(
        self,
        client: _OptionsFlowClient | None,
        search_type: str,
        errors: dict[str, str],
    ) -> None:
        """Load the selected radio catalog if needed."""
        if (
            client is None
            or search_type not in RADIO_CATALOG_SEARCH_TYPES
            or search_type in self._radio_catalogs
        ):
            return
        try:
            self._radio_catalogs[search_type] = await client.list_radio_catalog(search_type)
        except DHEError:
            errors["base"] = "radio_catalog_failed"

    def _validate_radio_catalog_input(
        self,
        *,
        user_input: dict[str, Any],
        search_type: str,
        catalog_options: dict[str, str],
        errors: dict[str, str],
    ) -> tuple[str, str | None] | None:
        """Validate radio search inputs and return normalized search values."""
        catalog_value = str(user_input.get(ATTR_RADIO_SELECTION, "")).strip()
        search_text = str(user_input.get(ATTR_RADIO_FILTER_TEXT, "")).strip()
        if search_type in RADIO_CATALOG_SEARCH_TYPES and not catalog_value:
            errors[ATTR_RADIO_SELECTION] = "required"
            return None
        if (
            search_type in RADIO_CATALOG_SEARCH_TYPES
            and catalog_options
            and catalog_value not in catalog_options
        ):
            errors[ATTR_RADIO_SELECTION] = "invalid_radio_catalog_value"
            return None
        if (
            search_type == "text" or search_type in RADIO_FILTER_SEARCH_TYPES
        ) and not search_text:
            errors[ATTR_RADIO_FILTER_TEXT] = "required"
            return None
        station_search_value = search_text if search_type == "text" else catalog_value
        station_search_text = (
            search_text if search_type in RADIO_FILTER_SEARCH_TYPES else None
        )
        return station_search_value, station_search_text

    async def _search_radio_results(
        self,
        client: _OptionsFlowClient,
        *,
        search_type: str,
        station_search_value: str,
        station_search_text: str | None,
        errors: dict[str, str],
    ) -> bool:
        """Search radio stations and store results; return True on success."""
        try:
            self._radio_results = await client.search_radio_stations(
                search_type,
                station_search_value,
                search_text=station_search_text,
            )
            if station_search_text:
                self._radio_results = _filter_radio_results_by_text(
                    self._radio_results,
                    station_search_text,
                )
        except DHEError:
            errors["base"] = "radio_search_failed"
            return False
        if not self._radio_results:
            errors["base"] = "no_results"
            return False
        return True

    async def async_step_radio_favorite_catalog(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Search DHE radio stations by a selected catalog value."""
        errors: dict[str, str] = {}
        client = self._client_or_mark_not_loaded(errors)
        defaults = user_input or {}
        search_type = self._effective_radio_search_type()
        await self._ensure_radio_catalog(client, search_type, errors)

        catalog_options = (
            _radio_catalog_options(self._radio_catalogs.get(search_type, []))
            if search_type in RADIO_CATALOG_SEARCH_TYPES
            else {}
        )
        if (
            search_type in RADIO_CATALOG_SEARCH_TYPES
            and not catalog_options
            and not errors
        ):
            errors["base"] = "no_radio_catalog"

        if user_input is not None and not errors and client is not None:
            validated = self._validate_radio_catalog_input(
                user_input=user_input,
                search_type=search_type,
                catalog_options=catalog_options,
                errors=errors,
            )
            if validated is not None:
                station_search_value, station_search_text = validated
                success = await self._search_radio_results(
                    client,
                    search_type=search_type,
                    station_search_value=station_search_value,
                    station_search_text=station_search_text,
                    errors=errors,
                )
                if success:
                    return await self.async_step_radio_favorite_result()

        return self.async_show_form(
            step_id="radio_favorite_catalog",
            data_schema=_radio_catalog_schema(search_type, catalog_options, defaults),
            errors=errors,
        )

    async def async_step_radio_favorite_result(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Select one radio station search result and save it as favorite."""
        errors: dict[str, str] = {}
        client = self._client_or_mark_not_loaded(errors)
        result_options = _radio_result_options(
            self._radio_results,
            max_options=MAX_RADIO_RESULT_OPTIONS,
        )

        if not result_options and "base" not in errors:
            errors["base"] = "no_results"

        if user_input is not None and not errors and client is not None:
            try:
                selected = int(user_input[ATTR_RESULT])
                station = self._radio_results[selected]
                await client.add_radio_favorite(station, select=True)
            except (IndexError, TypeError, ValueError):
                errors[ATTR_RESULT] = "invalid_result"
            except DHEError:
                errors["base"] = "radio_favorite_failed"
            else:
                return self._finish_options()

        return self.async_show_form(
            step_id="radio_favorite_result",
            data_schema=vol.Schema({vol.Required(ATTR_RESULT): vol.In(result_options)}),
            errors=errors,
        )

    async def async_step_remove_radio_favorite(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Remove a DHE radio favorite."""
        errors: dict[str, str] = {}
        client = self._client_or_mark_not_loaded(errors)
        if client is not None and user_input is None:
            try:
                self._radio_favorites = await client.list_radio_favorites()
            except DHEError:
                errors["base"] = "cannot_connect"

        favorite_options = _radio_result_options(
            self._radio_favorites,
            max_options=MAX_RADIO_RESULT_OPTIONS,
        )
        if not favorite_options and not errors:
            errors["base"] = "no_radio_favorites"

        if user_input is not None and not errors and client is not None:
            try:
                selected = int(user_input[ATTR_RESULT])
                station = self._radio_favorites[selected]
                await client.remove_radio_favorite(station)
            except (IndexError, TypeError, ValueError):
                errors[ATTR_RESULT] = "invalid_result"
            except DHEError:
                errors["base"] = "remove_radio_favorite_failed"
            else:
                return self._finish_options()

        return self.async_show_form(
            step_id="remove_radio_favorite",
            data_schema=vol.Schema({vol.Required(ATTR_RESULT): vol.In(favorite_options)}),
            errors=errors,
        )

    def _client(self) -> _OptionsFlowClient | None:
        """Return the runtime DHE client for this config entry."""
        runtime = getattr(self.config_entry, "runtime_data", None)
        return cast(_OptionsFlowClient | None, getattr(runtime, "client", None))
