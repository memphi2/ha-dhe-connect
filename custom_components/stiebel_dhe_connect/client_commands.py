"""Command and feature write helpers for the DHE client."""

from __future__ import annotations

import asyncio
import contextlib
import random
import time
from typing import Any

from .client_constants import APP_COMMAND_CONFIRMATION_TIMEOUT
from .client_mapping import (
    copy_json_like_value as _copy_json_like_value,
    radio_station_in_list as _radio_station_in_list,
    radio_station_input_id as _radio_station_input_id,
    weather_location_has_id as _weather_location_has_id,
    weather_location_id as _weather_location_id,
    weather_location_in_list as _weather_location_in_list,
)
from .client_types import DHEError, DHESession, MeasurementValue, ODBValue
from .client_value_helpers import (
    build_req66 as _build_req66,
    build_temperature_memory_button_value as _build_temperature_memory_button_value,
    c_to_raw_tenths as _c_to_raw_tenths,
    clamp as _clamp,
    raw_to_float as _raw_to_float,
    round_to_half_c as _round_to_half_c,
    values_equal as _values_equal,
    water_heating_enabled_to_raw as _water_heating_enabled_to_raw,
)
from .flow_helpers import (
    request_generation_and_wait as _request_generation_and_wait,
    wait_for_or_refresh as _wait_for_or_refresh,
)
from .protocol import (
    BRUSH_TIMER_PATH,
    CIRCULATION_SUPPORT_PROGRAM_ID,
    CO2_EMISSION_MAX,
    CURRENCY_GET_COMMAND,
    DEFAULT_NEW_TEMPERATURE_MEMORY_C,
    DEFAULT_TEMPERATURE_MEMORY_NAMES,
    ELECTRICITY_PRICE_MAX,
    ID_BATH_FILL_ACTIVE,
    ID_BATH_FILL_TARGET_VOLUME,
    ID_BRUSH_TIMER_ACTIVATION,
    ID_BRUSH_TIMER_DURATION,
    ID_BRUSH_TIMER_REMAINING,
    ID_CHILD_SAFETY_ACTIVE,
    ID_CHILD_SAFETY_TEMPERATURE_LIMIT,
    ID_CO2_EMISSION_RAW,
    ID_ECO_FLOW_LIMIT,
    ID_ECO_MODE,
    ID_ELECTRICITY_PRICE_CENTS,
    ID_ELECTRICITY_PRICE_EUROS,
    ID_SETPOINT_REQUEST,
    ID_SHOWER_TIMER_ACTIVATION,
    ID_SHOWER_TIMER_DURATION,
    ID_SHOWER_TIMER_REMAINING,
    ID_WATER_HEATING_ENABLED,
    ID_WATER_PRICE_CENTS,
    ID_WATER_PRICE_EUROS,
    ID_WELLNESS_ACTIVE,
    ID_WELLNESS_SHOWER_PROGRAM,
    ODB_ASSIGN_COMMAND,
    RADIO_ASSIGN_COMMANDS,
    RADIO_CATALOG_GET_COMMANDS,
    RADIO_FAVORITES_GET_COMMAND,
    RADIO_FAVORITE_ASSIGN_COMMAND,
    RADIO_PATH,
    RADIO_STATIONS_GET_COMMAND,
    RADIO_STATION_ASSIGN_COMMAND,
    RADIO_STATION_SEARCH_FIELDS,
    SET_REQ_OFF_VALUE,
    SHOWER_TIMER_PATH,
    SUMMER_FITNESS_PROGRAM_ID,
    TEMPERATURE_MEMORY_ID_TO_MEASUREMENT,
    TEMPERATURE_MEMORY_MAX_SLOTS,
    TEMPERATURE_MEMORY_SLOT_IDS,
    TEMPERATURE_MEMORY_SLOT_MEASUREMENTS,
    TEMP_MEMORY_ASSIGN_COMMAND,
    TEMP_MEMORY_GET_COMMAND,
    WATER_PRICE_MAX,
    WEATHER_COUNTRIES_GET_COMMAND,
    WEATHER_FAVORITES_GET_COMMAND,
    WEATHER_FAVORITE_ASSIGN_COMMAND,
    WEATHER_FORECAST_GET_COMMAND,
    WEATHER_LOCATION_GET_COMMAND,
    WELLNESS_COLD_PREVENTION_PROGRAM_ID,
    WINTER_REFRESH_PROGRAM_ID,
)


class DHEClientCommandsMixin:
    """User-facing write commands and feature-specific helpers."""

    async def set_temperature(self, temperature: float) -> float:
        requested = _round_to_half_c(_clamp(float(temperature), 20.0, 60.0))

        async def _operation(ctx: DHESession) -> float:
            addr = random.randint(1, 63)
            req_value = _build_req66(requested, addr)
            future = self._new_setpoint_future(requested)
            await self._post_packet(ctx, self._message_packet({
                "command": ODB_ASSIGN_COMMAND,
                "value": {"id": ID_SETPOINT_REQUEST, "value": req_value},
            }))
            readback = await self._wait_for_setpoint_confirmation(ctx, future)
            if abs(readback - requested) < 0.01:
                return readback
            raise DHEError(f"readback was {readback:.1f} C, expected {requested:.1f} C")

        return await self._run_command_with_reconnect_retry(
            "Could not set DHE setpoint",
            _operation,
            on_error=lambda: self._clear_pending_future(None),
        )

    async def set_heating_off(self) -> None:
        """Backward-compatible wrapper for the known DHE sync request."""
        await self._send_set_req_sync()

    async def set_water_heating_enabled(self, enabled: bool) -> bool:
        """Enable or disable water heating via ODB id 33 and sync request."""
        requested = bool(enabled)
        confirmed = bool(
            await self.write_odb_value(
                ID_WATER_HEATING_ENABLED,
                _water_heating_enabled_to_raw(requested),
            )
        )
        await self._send_set_req_sync()
        return confirmed

    async def _send_set_req_sync(self) -> None:
        """Send the observed ID 66 sync request used by the native app."""

        async def _operation(ctx: DHESession) -> None:
            await self._post_packet(
                ctx,
                self._message_packet(
                    {
                        "command": ODB_ASSIGN_COMMAND,
                        "value": {
                            "id": ID_SETPOINT_REQUEST,
                            "value": SET_REQ_OFF_VALUE,
                        },
                    }
                ),
            )

        await self._run_command_with_reconnect_retry(
            "Could not send DHE set-req sync",
            _operation,
        )

    async def write_odb_value(self, odb_id: int, value: Any) -> ODBValue:
        expected = self._convert_odb_value(odb_id, value)

        async def _operation(ctx: DHESession) -> ODBValue:
            future = self._new_write_future(odb_id, expected)
            await self._post_packet(ctx, self._message_packet({
                "command": ODB_ASSIGN_COMMAND,
                "value": {"id": int(odb_id), "value": value},
            }))
            confirmed = await self._wait_for_write_confirmation(ctx, future, odb_id)
            if _values_equal(confirmed, expected):
                return confirmed
            raise DHEError(f"write confirmation was {confirmed!r}, expected {expected!r}")

        return await self._run_command_with_reconnect_retry(
            f"Could not write DHE ODB id {odb_id}",
            _operation,
            on_error=lambda: self._clear_pending_write_future(None),
        )

    async def start_bath_fill(self) -> bool:
        return bool(await self.write_odb_value(ID_BATH_FILL_ACTIVE, True))

    async def stop_bath_fill(self) -> bool:
        return bool(await self.write_odb_value(ID_BATH_FILL_ACTIVE, False))

    async def set_bath_fill_target_volume(self, liters: float) -> float:
        requested = round(_clamp(float(liters), 5.0, 200.0))
        return float(await self.write_odb_value(ID_BATH_FILL_TARGET_VOLUME, requested))

    async def set_child_safety_temperature_limit(self, temperature: float) -> float:
        requested = _round_to_half_c(_clamp(float(temperature), 20.0, 60.0))
        return float(
            await self.write_odb_value(
                ID_CHILD_SAFETY_TEMPERATURE_LIMIT,
                _c_to_raw_tenths(requested),
            )
        )

    async def set_child_safety_active(self, enabled: bool) -> bool:
        return bool(await self.write_odb_value(ID_CHILD_SAFETY_ACTIVE, bool(enabled)))

    async def set_eco_mode(self, enabled: bool) -> bool:
        return bool(await self.write_odb_value(ID_ECO_MODE, bool(enabled)))

    async def set_eco_flow_limit(self, liters_per_minute: float) -> float:
        requested_l_min = _round_to_half_c(_clamp(float(liters_per_minute), 4.0, 15.0))
        raw_value = round(requested_l_min * 10.0)
        return float(await self.write_odb_value(ID_ECO_FLOW_LIMIT, raw_value))

    async def set_electricity_price(self, euros_per_kwh: float) -> float:
        return await self._set_price(
            euros_per_kwh,
            ID_ELECTRICITY_PRICE_EUROS,
            ID_ELECTRICITY_PRICE_CENTS,
            max_value=ELECTRICITY_PRICE_MAX,
        )

    async def set_water_price(self, euros_per_m3: float) -> float:
        return await self._set_price(
            euros_per_m3,
            ID_WATER_PRICE_EUROS,
            ID_WATER_PRICE_CENTS,
            max_value=WATER_PRICE_MAX,
        )

    async def set_co2_emission(self, kg_per_kwh: float) -> float:
        value = round(_clamp(float(kg_per_kwh), 0.0, CO2_EMISSION_MAX), 3)
        raw_value = self._co2_emission_to_raw(value)
        await self.write_odb_value(ID_CO2_EMISSION_RAW, raw_value)
        return value

    async def set_currency(self, currency: str) -> str:
        requested = str(currency).strip().lower()
        if not requested:
            raise DHEError("Currency must not be empty")

        async def _operation(ctx: DHESession) -> str:
            await self._post_packet(ctx, self._message_packet({
                "command": CURRENCY_GET_COMMAND,
                "value": requested,
            }))
            self._handle_currency_value(requested, source_command=CURRENCY_GET_COMMAND)
            return requested.upper()

        return await self._run_command_with_reconnect_retry(
            "Could not set DHE currency",
            _operation,
        )

    async def set_radio_play(self, play: bool) -> bool:
        requested = bool(play)
        await self._assign_radio_value("play", requested)
        self._handle_radio_value(f"assign:{RADIO_PATH}:play", requested)
        return requested

    async def set_radio_volume(self, volume_level: float) -> float:
        volume = round(_clamp(float(volume_level), 0.0, 1.0) * 100.0)
        await self._assign_radio_value("volume", volume)
        self._handle_radio_value(f"assign:{RADIO_PATH}:volume", volume)
        return volume / 100.0

    async def disconnect_radio_pairing(self) -> bool:
        """Send the DHE radio pairing disconnect action."""
        await self._assign_radio_value("paired", False)
        self._handle_radio_value(f"assign:{RADIO_PATH}:paired", False)
        return True

    async def list_radio_genres(self) -> list[str]:
        """Return the DHE radio genre catalog."""
        return await self.list_radio_catalog("genre")

    async def list_radio_catalog(self, attribute: str) -> list[str]:
        """Return a DHE radio station search catalog."""
        requested_attribute = str(attribute).strip().lower()
        command = RADIO_CATALOG_GET_COMMANDS.get(requested_attribute)
        if command is None:
            raise DHEError(f"Unsupported DHE radio catalog: {attribute}")

        async def _operation(ctx: DHESession) -> list[str]:
            generation = self._radio_catalog_generations[requested_attribute]
            await self._request_app_value(ctx, command)
            return await self._wait_for_radio_catalog(
                requested_attribute,
                generation,
            )

        return await self._run_command_with_reconnect_retry(
            f"Could not read DHE radio {requested_attribute} catalog",
            _operation,
        )

    async def search_radio_stations_by_genre(self, genre: str) -> list[dict[str, Any]]:
        """Search radio stations by DHE radio genre path."""
        return await self.search_radio_stations("genre", genre)

    async def search_radio_stations(
        self,
        attribute: str,
        value: str,
        *,
        search_text: str | None = None,
    ) -> list[dict[str, Any]]:
        requested_attribute = str(attribute).strip().lower()
        requested_value = str(value).strip()
        requested_search_text = (
            str(search_text).strip() if search_text is not None else ""
        )
        if requested_attribute not in RADIO_STATION_SEARCH_FIELDS:
            raise DHEError(f"Unsupported DHE radio station search: {attribute}")
        if not requested_value:
            raise DHEError("Radio station search value must not be empty")
        if search_text is not None and not requested_search_text:
            raise DHEError("Radio station search text must not be empty")
        search_payload = {
            "attribute": requested_attribute,
            "value": requested_value,
        }
        if requested_search_text:
            search_payload["text"] = requested_search_text

        async def _operation(ctx: DHESession) -> list[dict[str, Any]]:
            generation = self._radio_stations_generation
            await self._post_packet(ctx, self._message_packet({
                "command": RADIO_STATIONS_GET_COMMAND,
                "value": search_payload,
            }))
            return await self._wait_for_radio_stations(generation)

        return await self._run_command_with_reconnect_retry(
            "Could not search DHE radio stations",
            _operation,
        )

    async def list_radio_favorites(self) -> list[dict[str, Any]]:
        """Return DHE radio favorites."""
        async def _operation(ctx: DHESession) -> list[dict[str, Any]]:
            return await self._request_radio_favorites(ctx)

        return await self._run_command_with_reconnect_retry(
            "Could not read DHE radio favorites",
            _operation,
        )

    def _require_radio_station_id(self, station: dict[str, Any] | int | str) -> int:
        station_id = _radio_station_input_id(station)
        if station_id is None:
            raise DHEError("Radio station must include Id")
        return station_id

    async def _request_radio_favorites(self, ctx: DHESession) -> list[dict[str, Any]]:
        return await _request_generation_and_wait(
            lambda: self._request_app_value(ctx, RADIO_FAVORITES_GET_COMMAND),
            lambda: self._radio_favorites_generation,
            self._wait_for_radio_favorites,
        )

    async def _assign_radio_favorite_and_wait(
        self,
        ctx: DHESession,
        station_id: int,
    ) -> list[dict[str, Any]]:
        generation = self._radio_favorites_generation
        await self._send_ste_command(ctx, RADIO_FAVORITE_ASSIGN_COMMAND, station_id)
        return await _wait_for_or_refresh(
            lambda: self._wait_for_radio_favorites(generation),
            lambda: self._request_app_value(ctx, RADIO_FAVORITES_GET_COMMAND),
            retry_exceptions=(DHEError,),
        )

    async def add_radio_favorite(
        self,
        station: dict[str, Any] | int | str,
        *,
        select: bool = True,
    ) -> bool:
        """Add a radio station favorite and optionally select it."""
        station_id = self._require_radio_station_id(station)

        async def _operation(ctx: DHESession) -> bool:
            favorites = self._radio_favorites()
            is_favorite = _radio_station_in_list(station_id, favorites)
            try:
                favorites = await self._request_radio_favorites(ctx)
                is_favorite = _radio_station_in_list(station_id, favorites)
            except DHEError as err:
                if not is_favorite:
                    raise DHEError(
                        "Cannot safely add DHE radio favorite without a fresh favorite list"
                    ) from err

            if not is_favorite:
                favorites = await self._assign_radio_favorite_and_wait(ctx, station_id)
                is_favorite = _radio_station_in_list(station_id, favorites)
                if not is_favorite:
                    raise DHEError(f"DHE radio favorite {station_id} did not change")

            if select:
                await self._send_ste_command(
                    ctx,
                    RADIO_STATION_ASSIGN_COMMAND,
                    station_id,
                )
                with contextlib.suppress(DHEError):
                    await self._wait_for_radio_station(station_id)
            return True

        return await self._run_command_with_reconnect_retry(
            "Could not add DHE radio favorite",
            _operation,
        )

    async def remove_radio_favorite(self, station: dict[str, Any] | int | str) -> bool:
        """Remove a radio station favorite."""
        station_id = self._require_radio_station_id(station)

        async def _operation(ctx: DHESession) -> bool:
            favorites = await self._request_radio_favorites(ctx)
            is_favorite = _radio_station_in_list(station_id, favorites)
            if not is_favorite:
                return True

            favorites = await self._assign_radio_favorite_and_wait(ctx, station_id)
            is_favorite = _radio_station_in_list(station_id, favorites)
            if is_favorite:
                raise DHEError("DHE radio favorite did not change")
            return True

        return await self._run_command_with_reconnect_retry(
            "Could not remove DHE radio favorite",
            _operation,
        )

    async def select_radio_station(self, station: dict[str, Any] | int | str) -> bool:
        """Select/play a radio station by station payload or station ID."""
        station_id = self._require_radio_station_id(station)

        async def _operation(ctx: DHESession) -> bool:
            await self._send_ste_command(ctx, RADIO_STATION_ASSIGN_COMMAND, station_id)
            with contextlib.suppress(DHEError):
                await self._wait_for_radio_station(station_id)
            return True

        return await self._run_command_with_reconnect_retry(
            "Could not select DHE radio station",
            _operation,
        )

    async def search_weather_locations(
        self,
        name: str,
        country_id: int | float | str,
    ) -> list[dict[str, Any]]:
        requested_name = str(name).strip()
        if not requested_name:
            raise DHEError("Weather location search name must not be empty")
        requested_country_id = int(_raw_to_float(country_id))

        async def _operation(ctx: DHESession) -> list[dict[str, Any]]:
            generation = self._weather_search_generation
            await self._post_packet(ctx, self._message_packet({
                "command": WEATHER_FORECAST_GET_COMMAND,
                "value": {
                    "name": requested_name,
                    "countryId": requested_country_id,
                },
            }))
            return await self._wait_for_weather_search_results(generation)

        return await self._run_command_with_reconnect_retry(
            "Could not search DHE weather locations",
            _operation,
        )

    async def list_weather_countries(self) -> list[dict[str, Any]]:
        """Return the weather country catalog from the DHE."""
        async def _operation(ctx: DHESession) -> list[dict[str, Any]]:
            generation = self._weather_countries_generation
            await self._request_app_value(ctx, WEATHER_COUNTRIES_GET_COMMAND)
            return await self._wait_for_weather_countries(generation)

        return await self._run_command_with_reconnect_retry(
            "Could not read DHE weather countries",
            _operation,
        )

    async def toggle_weather_favorite(self, location: dict[str, Any]) -> bool:
        if not _weather_location_has_id(location):
            raise DHEError("Weather favorite location must include LocationId")

        async def _operation(ctx: DHESession) -> bool:
            payload = _copy_json_like_value(location)
            await self._assign_weather_favorite_and_wait(ctx, payload)
            return True

        return await self._run_command_without_reconnect_retry(
            "Could not toggle DHE weather favorite",
            _operation,
        )

    async def list_weather_favorites(self) -> list[dict[str, Any]]:
        """Return the weather favorites from the DHE."""
        async def _operation(ctx: DHESession) -> list[dict[str, Any]]:
            return await self._request_weather_favorites(ctx)

        return await self._run_command_with_reconnect_retry(
            "Could not read DHE weather favorites",
            _operation,
        )

    async def add_weather_favorite(self, location: dict[str, Any]) -> bool:
        """Add a weather favorite without toggling an existing favorite off."""
        if not _weather_location_has_id(location):
            raise DHEError("Weather favorite location must include LocationId")

        async def _operation(ctx: DHESession) -> bool:
            payload = _copy_json_like_value(location)

            favorites = self._weather_favorites()
            is_favorite = _weather_location_in_list(payload, favorites)
            try:
                favorites = await self._request_weather_favorites(ctx)
                is_favorite = _weather_location_in_list(payload, favorites)
            except DHEError as err:
                if is_favorite:
                    return True

                raise DHEError(
                    "Cannot safely add DHE weather favorite without a fresh favorite list"
                ) from err
            if is_favorite:
                return True

            location_id = _weather_location_id(payload)
            favorites = await self._assign_weather_favorite_and_wait(ctx, payload)
            is_favorite = _weather_location_in_list(payload, favorites)
            if not is_favorite:
                raise DHEError("DHE weather favorite did not change")
            await self._send_ste_command(ctx, WEATHER_LOCATION_GET_COMMAND, location_id)
            await self._wait_for_weather_location(location_id)
            return True

        return await self._run_command_with_reconnect_retry(
            "Could not add DHE weather favorite",
            _operation,
        )

    async def remove_weather_favorite(self, location: dict[str, Any]) -> bool:
        """Remove a weather favorite without toggling a missing favorite on."""
        if not _weather_location_has_id(location):
            raise DHEError("Weather favorite location must include LocationId")

        async def _operation(ctx: DHESession) -> bool:
            payload = _copy_json_like_value(location)
            favorites = self._weather_favorites()
            try:
                favorites = await self._request_weather_favorites(ctx)
            except DHEError as err:
                raise DHEError(
                    "Cannot safely remove DHE weather favorite without a fresh "
                    "favorite list"
                ) from err

            is_favorite = _weather_location_in_list(payload, favorites)
            if not is_favorite:
                return True

            favorites = await self._assign_weather_favorite_and_wait(ctx, payload)
            is_favorite = _weather_location_in_list(payload, favorites)
            if is_favorite:
                raise DHEError("DHE weather favorite did not change")
            return True

        return await self._run_command_with_reconnect_retry(
            "Could not remove DHE weather favorite",
            _operation,
        )

    async def select_weather_location(self, location: dict[str, Any] | str) -> bool:
        if isinstance(location, dict):
            location_id = location.get("LocationId")
        else:
            location_id = location
        requested_location_id = str(location_id or "").strip()
        if not requested_location_id:
            raise DHEError("Weather location must include LocationId")

        async def _operation(ctx: DHESession) -> bool:
            await self._send_ste_command(
                ctx,
                WEATHER_LOCATION_GET_COMMAND,
                requested_location_id,
            )
            await self._wait_for_weather_location(requested_location_id)
            return True

        return await self._run_command_with_reconnect_retry(
            "Could not select DHE weather location",
            _operation,
        )

    async def _request_weather_favorites(self, ctx: DHESession) -> list[dict[str, Any]]:
        return await _request_generation_and_wait(
            lambda: self._request_app_value(ctx, WEATHER_FAVORITES_GET_COMMAND),
            lambda: self._weather_favorites_generation,
            self._wait_for_weather_favorites,
        )

    async def _assign_weather_favorite_and_wait(
        self,
        ctx: DHESession,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        generation = self._weather_favorites_generation
        await self._send_ste_command(ctx, WEATHER_FAVORITE_ASSIGN_COMMAND, payload)
        return await _wait_for_or_refresh(
            lambda: self._wait_for_weather_favorites(generation),
            lambda: self._request_app_value(ctx, WEATHER_FAVORITES_GET_COMMAND),
            retry_exceptions=(DHEError,),
        )

    async def _assign_radio_value(self, field: str, value: Any) -> None:
        command = f"assign:{RADIO_PATH}:{field}"
        if command not in RADIO_ASSIGN_COMMANDS:
            raise DHEError(f"Unsupported DHE radio assignment: {field}")

        async def _operation(ctx: DHESession) -> None:
            await self._send_ste_command(ctx, command, value)

        await self._run_command_with_reconnect_retry(
            f"Could not write DHE radio {field}",
            _operation,
        )

    async def _set_price(
        self,
        value: float,
        euros_odb_id: int,
        cents_odb_id: int,
        *,
        max_value: float,
    ) -> float:
        old_euros = self._last_measurements.get(euros_odb_id)
        old_cents = self._last_measurements.get(cents_odb_id)
        total_cents = round(_clamp(float(value), 0.0, max_value) * 100)
        euros, cents = divmod(total_cents, 100)
        attempted_components: list[tuple[int, MeasurementValue]] = []
        try:
            attempted_components.append((euros_odb_id, old_euros))
            await self.write_odb_value(euros_odb_id, euros)
            attempted_components.append((cents_odb_id, old_cents))
            await self.write_odb_value(cents_odb_id, cents)
        except (DHEError, RuntimeError) as err:
            rollback_errors = await self._rollback_price_components(attempted_components)
            if rollback_errors:
                raise DHEError(
                    f"{err}; price rollback failed: {'; '.join(rollback_errors)}"
                ) from err
            raise
        return total_cents / 100.0

    async def _rollback_price_components(
        self,
        components: list[tuple[int, MeasurementValue]],
    ) -> list[str]:
        """Best-effort restore of price components after a partial write."""
        errors: list[str] = []
        for odb_id, old_value in reversed(components):
            if old_value is None:
                continue
            try:
                await self.write_odb_value(odb_id, old_value)
            except (DHEError, RuntimeError) as err:
                errors.append(f"ODB id {odb_id}: {err}")
        return errors

    async def press_temperature_memory(self, memory_slot: int) -> bool:
        try:
            memory_id = TEMPERATURE_MEMORY_SLOT_IDS[int(memory_slot)]
            measurement_id = TEMPERATURE_MEMORY_ID_TO_MEASUREMENT[memory_id]
        except KeyError as err:
            raise DHEError(f"Unsupported temperature memory slot: {memory_slot}") from err

        async def _operation(ctx: DHESession) -> bool:
            temperature = await self._get_temperature_memory_temperature(
                ctx,
                memory_slot,
                measurement_id,
            )
            request_value = _build_temperature_memory_button_value(temperature)
            await self._post_packet(ctx, self._message_packet({
                "command": ODB_ASSIGN_COMMAND,
                "value": {"id": ID_SETPOINT_REQUEST, "value": request_value},
            }))
            with contextlib.suppress(DHEError):
                await self._request_setpoint(ctx)
            return True

        return await self._run_command_with_reconnect_retry(
            f"Could not press DHE temperature memory {memory_slot}",
            _operation,
        )

    async def _get_temperature_memory_temperature(
        self,
        ctx: DHESession,
        memory_slot: int,
        measurement_id: int,
    ) -> float:
        temperature = self._cached_temperature_memory_temperature(measurement_id)
        if temperature is not None:
            return temperature

        await self._request_app_value(ctx, TEMP_MEMORY_GET_COMMAND)
        deadline = time.monotonic() + APP_COMMAND_CONFIRMATION_TIMEOUT
        while time.monotonic() < deadline:
            temperature = self._cached_temperature_memory_temperature(measurement_id)
            if temperature is not None:
                return temperature
            await asyncio.sleep(0.1)
        raise DHEError(f"DHE temperature memory {memory_slot} is not available yet")

    async def _refresh_temperature_memories(self, ctx: DHESession) -> None:
        generation = self._temperature_memory_generation
        await self._request_app_value(ctx, TEMP_MEMORY_GET_COMMAND)
        deadline = time.monotonic() + APP_COMMAND_CONFIRMATION_TIMEOUT
        while time.monotonic() < deadline:
            if self._temperature_memory_generation != generation:
                return
            await asyncio.sleep(0.1)

    def _cached_temperature_memory_temperature(self, measurement_id: int) -> float | None:
        value = self._last_measurements.get(measurement_id)
        if value is None or isinstance(value, bool):
            return None
        return _round_to_half_c(_clamp(float(value), 20.0, 60.0))

    def _temperature_memory_ids(self, memory_slot: int) -> tuple[int, int]:
        try:
            slot = int(memory_slot)
            memory_id = TEMPERATURE_MEMORY_SLOT_IDS[slot]
            measurement_id = TEMPERATURE_MEMORY_SLOT_MEASUREMENTS[slot]
        except KeyError as err:
            raise DHEError(f"Unsupported temperature memory slot: {memory_slot}") from err
        return memory_id, measurement_id

    def _temperature_memory_exists(self, memory_id: int, measurement_id: int) -> bool:
        return memory_id in self._temperature_memory_ids_seen or measurement_id in self._last_measurements

    def _can_create_temperature_memory(self, memory_id: int) -> bool:
        if len(self._temperature_memory_ids_seen) >= TEMPERATURE_MEMORY_MAX_SLOTS:
            return False
        if not self._temperature_memory_ids_seen:
            return memory_id == 0
        return memory_id == max(self._temperature_memory_ids_seen) + 1

    def _temperature_memory_payload(
        self,
        memory_id: int,
        measurement_id: int,
        name: str,
        temperature: float,
    ) -> dict[str, Any]:
        exists = self._temperature_memory_exists(memory_id, measurement_id)
        if not exists and not self._can_create_temperature_memory(memory_id):
            raise DHEError("Temperature memories must be created in order")

        payload: dict[str, Any] = {
            "name": name,
            "temperature": temperature,
            "operation": "add_change",
        }
        if exists:
            payload["id"] = memory_id
        return payload

    async def set_temperature_memory(self, memory_slot: int, temperature: float) -> float:
        memory_id, measurement_id = self._temperature_memory_ids(memory_slot)

        requested = _round_to_half_c(_clamp(float(temperature), 20.0, 60.0))

        async def _operation(ctx: DHESession) -> float:
            await self._refresh_temperature_memories(ctx)
            before_generation = self._temperature_memory_generation
            attributes = self._last_measurement_attributes.get(measurement_id, {})
            name = str(attributes.get("name", DEFAULT_TEMPERATURE_MEMORY_NAMES[memory_id]))
            payload = self._temperature_memory_payload(
                memory_id,
                measurement_id,
                name,
                requested,
            )
            await self._post_packet(ctx, self._message_packet({
                "command": TEMP_MEMORY_ASSIGN_COMMAND,
                "value": payload,
            }))
            await self._refresh_temperature_memories(ctx)
            if self._temperature_memory_generation == before_generation:
                raise DHEError(
                    f"DHE temperature memory {memory_slot} was not confirmed"
                )
            confirmed = self._cached_temperature_memory_temperature(measurement_id)
            if confirmed is None or abs(confirmed - requested) >= 0.01:
                raise DHEError(
                    f"DHE temperature memory {memory_slot} readback was {confirmed!r}, "
                    f"expected {requested!r}"
                )
            return confirmed

        return await self._run_command_with_reconnect_retry(
            f"Could not set DHE temperature memory {memory_slot}",
            _operation,
        )

    async def set_temperature_memory_name(self, memory_slot: int, name: str) -> str:
        memory_id, measurement_id = self._temperature_memory_ids(memory_slot)

        requested_name = str(name).strip()
        if not requested_name:
            raise DHEError(f"DHE temperature memory {memory_slot} name must not be empty")

        async def _operation(ctx: DHESession) -> str:
            await self._refresh_temperature_memories(ctx)
            before_generation = self._temperature_memory_generation
            temperature = (
                self._cached_temperature_memory_temperature(measurement_id)
                or DEFAULT_NEW_TEMPERATURE_MEMORY_C
            )
            payload = self._temperature_memory_payload(
                memory_id,
                measurement_id,
                requested_name,
                temperature,
            )
            await self._post_packet(ctx, self._message_packet({
                "command": TEMP_MEMORY_ASSIGN_COMMAND,
                "value": payload,
            }))
            await self._refresh_temperature_memories(ctx)
            if self._temperature_memory_generation == before_generation:
                raise DHEError(
                    f"DHE temperature memory {memory_slot} name was not confirmed"
                )
            attributes = self._last_measurement_attributes.get(measurement_id, {})
            confirmed_name = str(attributes.get("name", "")).strip()
            if confirmed_name != requested_name:
                raise DHEError(
                    f"DHE temperature memory {memory_slot} name readback was "
                    f"{confirmed_name!r}, expected {requested_name!r}"
                )
            return confirmed_name

        return await self._run_command_with_reconnect_retry(
            f"Could not set DHE temperature memory {memory_slot} name",
            _operation,
        )

    async def delete_temperature_memory(self, memory_slot: int) -> bool:
        memory_id, measurement_id = self._temperature_memory_ids(memory_slot)

        async def _operation(ctx: DHESession) -> bool:
            await self._refresh_temperature_memories(ctx)
            if not self._temperature_memory_exists(memory_id, measurement_id):
                raise DHEError(f"DHE temperature memory {memory_slot} is not available")
            await self._post_packet(ctx, self._message_packet({
                "command": TEMP_MEMORY_ASSIGN_COMMAND,
                "value": {
                    "id": memory_id,
                    "operation": "delete",
                },
            }))
            await self._refresh_temperature_memories(ctx)
            if self._temperature_memory_exists(memory_id, measurement_id):
                raise DHEError(f"DHE temperature memory {memory_slot} was not deleted")
            return True

        return await self._run_command_with_reconnect_retry(
            f"Could not delete DHE temperature memory {memory_slot}",
            _operation,
        )

    async def set_wellness_cold_prevention(self, enabled: bool) -> bool:
        if enabled:
            await self.write_odb_value(ID_WELLNESS_SHOWER_PROGRAM, WELLNESS_COLD_PREVENTION_PROGRAM_ID)
            await self.write_odb_value(ID_WELLNESS_ACTIVE, True)
            return True

        await self.write_odb_value(ID_WELLNESS_ACTIVE, False)
        self._handle_measurement(ID_WELLNESS_ACTIVE, False, force_update=True)
        self._handle_measurement(ID_WELLNESS_SHOWER_PROGRAM, 0.0, force_update=True)
        return False

    async def set_wellness_shower_program(self, program_id: int) -> bool:
        await self.write_odb_value(ID_WELLNESS_SHOWER_PROGRAM, int(program_id))
        await self.write_odb_value(ID_WELLNESS_ACTIVE, True)
        return True

    async def stop_wellness_shower_program(self) -> bool:
        await self.write_odb_value(ID_WELLNESS_ACTIVE, False)
        self._handle_measurement(ID_WELLNESS_ACTIVE, False, force_update=True)
        self._handle_measurement(ID_WELLNESS_SHOWER_PROGRAM, 0.0, force_update=True)
        return False

    async def set_brush_timer_duration_minutes(self, minutes: float) -> float:
        return await self._set_app_timer_duration_minutes(
            BRUSH_TIMER_PATH,
            ID_BRUSH_TIMER_DURATION,
            minutes,
        )

    async def set_brush_timer_activation(self, enabled: bool) -> bool:
        return await self._set_app_timer_activation(
            BRUSH_TIMER_PATH,
            ID_BRUSH_TIMER_ACTIVATION,
            enabled,
        )

    async def set_shower_timer_duration_minutes(self, minutes: float) -> float:
        return await self._set_app_timer_duration_minutes(
            SHOWER_TIMER_PATH,
            ID_SHOWER_TIMER_DURATION,
            minutes,
        )

    async def set_shower_timer_activation(self, enabled: bool) -> bool:
        return await self._set_app_timer_activation(
            SHOWER_TIMER_PATH,
            ID_SHOWER_TIMER_ACTIVATION,
            enabled,
        )

    async def reset_brush_timer(self) -> bool:
        return await self._reset_app_timer(
            BRUSH_TIMER_PATH,
            ID_BRUSH_TIMER_ACTIVATION,
            ID_BRUSH_TIMER_REMAINING,
        )

    async def reset_shower_timer(self) -> bool:
        return await self._reset_app_timer(
            SHOWER_TIMER_PATH,
            ID_SHOWER_TIMER_ACTIVATION,
            ID_SHOWER_TIMER_REMAINING,
        )

    async def run_wellness_shower_program_winter_refresh(self) -> bool:
        """Trigger the wellness shower program 'Winter refresh'."""
        for _ in range(2):
            await self.write_odb_value(ID_WELLNESS_SHOWER_PROGRAM, WINTER_REFRESH_PROGRAM_ID)
            await self.write_odb_value(ID_WELLNESS_ACTIVE, True)
        return True

    async def run_wellness_shower_program_summer_fitness(self) -> bool:
        """Trigger the wellness shower program 'Summer fitness'."""
        for _ in range(2):
            await self.write_odb_value(ID_WELLNESS_SHOWER_PROGRAM, SUMMER_FITNESS_PROGRAM_ID)
            await self.write_odb_value(ID_WELLNESS_ACTIVE, True)
        return True

    async def run_wellness_shower_program_circulation_support(self) -> bool:
        """Trigger the wellness shower program 'Circulation support'."""
        for _ in range(2):
            await self.write_odb_value(ID_WELLNESS_SHOWER_PROGRAM, CIRCULATION_SUPPORT_PROGRAM_ID)
            await self.write_odb_value(ID_WELLNESS_ACTIVE, True)
        return True

    async def _set_app_timer_duration_minutes(
        self,
        path: str,
        measurement_id: int,
        minutes: float,
    ) -> float:
        requested_minutes = _clamp(float(minutes), 1.0, 20.0)
        milliseconds = round(requested_minutes * 60000.0)
        confirmed = await self._write_app_value(
            f"assign:{path}:durationMilliseconds",
            milliseconds,
            measurement_id,
            float(requested_minutes),
        )
        return float(confirmed)

    async def _set_app_timer_activation(self, path: str, measurement_id: int, enabled: bool) -> bool:
        confirmed = await self._write_app_value(
            f"assign:{path}:activation",
            bool(enabled),
            measurement_id,
            bool(enabled),
        )
        return bool(confirmed)

    async def _reset_app_timer(self, path: str, activation_id: int, remaining_id: int) -> bool:
        await self._write_app_value(
            f"assign:{path}:reset",
            True,
            remaining_id,
            0.0,
        )
        self._handle_measurement(remaining_id, 0.0, force_update=True)
        self._handle_measurement(activation_id, False, force_update=True)
        return True

    async def _write_app_value(self, command: str, value: Any, measurement_id: int, expected: ODBValue) -> ODBValue:
        async def _operation(ctx: DHESession) -> ODBValue:
            future = self._new_write_future(measurement_id, expected)
            await self._post_packet(ctx, self._message_packet({"command": command, "value": value}))
            try:
                return await self._wait_for_app_write_confirmation(future)
            except TimeoutError as err:
                self._clear_pending_write_future(None)
                raise DHEError(
                    f"No DHE app confirmation for {command} within "
                    f"{APP_COMMAND_CONFIRMATION_TIMEOUT:.1f}s"
                ) from err

        return await self._run_command_with_reconnect_retry(
            f"Could not write DHE app command {command}",
            _operation,
            on_error=lambda: self._clear_pending_write_future(None),
        )
