"""Runtime message handlers for the DHE client."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .client_constants import (
    APP_COMMAND_CONFIRMATION_TIMEOUT,
    COMMAND_CONFIRMATION_TIMEOUT,
    COMMAND_READBACK_INTERVAL,
    DEFAULT_NOMINAL_POWER_KW,
    ODB_READBACK_REQUEST_WINDOW_SECONDS,
    WEATHER_CATALOG_TIMEOUT,
)
from .client_diagnostics import (
    diagnostic_timestamp as _diagnostic_timestamp,
    summarize_diagnostic_value as _summarize_diagnostic_value,
    summarize_radio_value as _summarize_radio_value,
    summarize_weather_value as _summarize_weather_value,
)
from .client_mapping import (
    copy_dict_items as _copy_dict_items,
    copy_json_like_value as _copy_json_like_value,
    device_status_key as _device_status_key,
    device_status_problem as _device_status_problem,
    normalize_radio_stations_value as _normalize_radio_stations_value,
    normalize_radio_string_catalog as _normalize_radio_string_catalog,
    normalize_weather_favorites_value as _normalize_weather_favorites_value,
    normalize_weather_locations_value as _normalize_weather_locations_value,
    normalize_weather_value as _normalize_weather_value,
    radio_station_id as _radio_station_id,
)
from .client_runtime_app import DHEClientRuntimeAppMixin
from .client_types import (
    DHEError,
    DHEEvent,
    DHESession,
    DHESessionClosed,
    MeasurementValue,
    ODB_READ_SOURCE_REQUESTED,
    ODB_READ_SOURCE_RUNTIME,
    ODBReadSource,
    ODBValue,
)
from .client_value_helpers import (
    clamp as _clamp,
    raw_tenths_to_c as _raw_tenths_to_c,
    raw_to_bool as _raw_to_bool,
    raw_to_float as _raw_to_float,
    raw_to_water_heating_enabled as _raw_to_water_heating_enabled,
    should_publish_odb_readback as _should_publish_odb_readback,
    values_equal as _values_equal,
)
from .flow_helpers import (
    wait_for_generation_change as _wait_for_generation_change,
    wait_until as _wait_until,
)
from .protocol import (
    APP_STARTUP_SET_COMMANDS,
    APP_TIMER_RESET_COMMANDS,
    APP_TIMER_VALUE_COMMANDS,
    CO2_EMISSION_RAW_MAX,
    CONSUMPTION_COMMAND_IDS,
    CURRENCY_GET_COMMAND,
    CURRENCY_SET_COMMAND,
    DEVICE_INFO_COMMAND_IDS,
    ID_BATH_FILL_ACTIVE,
    ID_BATH_FILL_CURRENT_VOLUME,
    ID_BATH_FILL_REMAINING_VOLUME,
    ID_BATH_FILL_TARGET_VOLUME,
    ID_CHILD_SAFETY_ACTIVE,
    ID_CHILD_SAFETY_TEMPERATURE_LIMIT,
    ID_CO2_EMISSION,
    ID_CO2_EMISSION_RAW,
    ID_DEVICE_STATUS,
    ID_ECO_FLOW_LIMIT,
    ID_ECO_MODE,
    ID_NOMINAL_POWER,
    ID_POWER_PERCENT,
    ID_PROTOCOL_VERSION,
    ID_SCALD_PROTECTION_ACTIVE,
    ID_WATER_FLOW,
    ID_WATER_HEATING_ENABLED,
    ID_WELLNESS_ACTIVE,
    KNOWN_ODB_VALUE_IDS,
    LAST_USAGE_SET_COMMAND,
    ODB_ASSIGN_COMMAND,
    ODB_DEBUG_NAMES,
    ODB_DECILITER_VALUE_IDS,
    ODB_IGNORED_VALUE_IDS,
    ODB_NONNEGATIVE_VALUE_IDS,
    ODB_SET_COMMAND,
    ODB_TENTHS_TEMPERATURE_IDS,
    ODB_ZERO_REQUEST_READBACK_IGNORE_IDS,
    PRICE_CENTS_COMPONENT_MAX,
    PRICE_COMPONENT_IDS,
    PRICE_EUROS_COMPONENT_MAX_BY_ID,
    RADIO_ASSIGN_COMMANDS,
    RADIO_CATALOG_FIELDS,
    RADIO_FAVORITES_SET_COMMAND,
    RADIO_GENRE_SET_COMMAND,
    RADIO_KNOWN_REQUEST_COMMANDS,
    RADIO_PATH,
    RADIO_SET_COMMANDS,
    RADIO_STATIONS_SET_COMMAND,
    SAVING_MONITOR_COMMAND_IDS,
    TEMP_MEMORY_ASSIGN_COMMAND,
    TEMP_MEMORY_SET_COMMAND,
    WEATHER_ASSIGN_COMMANDS,
    WEATHER_COUNTRIES_SET_COMMAND,
    WEATHER_COUNTRY_SET_COMMAND,
    WEATHER_FAVORITES_SET_COMMAND,
    WEATHER_FORECAST_SET_COMMAND,
    WEATHER_LOCATION_SET_COMMAND,
    WEATHER_SET_COMMANDS,
    WRITABLE_OPTION_IDS,
)

_LOGGER = logging.getLogger(__name__)
_MISSING_MEASUREMENT = object()


class DHEClientRuntimeMixin(DHEClientRuntimeAppMixin):
    """Runtime event dispatch, state updates and readback waiters."""

    async def _handle_runtime_event(self, event: DHEEvent) -> None:
        if event.name == "__closed":
            self._update_diagnostics(
                connection_state="reconnecting",
                last_reconnect_reason="DHE closed Socket.IO session",
            )
            raise DHESessionClosed("DHE closed Socket.IO session")
        if event.name != "message" or not isinstance(event.data, dict):
            return
        data = event.data
        command = data.get("command")
        value = data.get("value")
        self._record_runtime_message(command, value)
        is_radio_command = isinstance(command, str) and RADIO_PATH in command
        if command in APP_TIMER_RESET_COMMANDS:
            self._handle_app_timer_reset(command)
            return
        if command in APP_TIMER_VALUE_COMMANDS:
            self._handle_app_timer_value(command, value)
            return
        if command in RADIO_KNOWN_REQUEST_COMMANDS:
            self._last_app_values[command] = _summarize_radio_value(value)
            return
        if command == RADIO_STATIONS_SET_COMMAND:
            self._handle_radio_stations_value(value)
            return
        if command == RADIO_FAVORITES_SET_COMMAND:
            self._handle_radio_favorites_value(value)
            return
        if command in RADIO_ASSIGN_COMMANDS:
            self._last_app_values[command] = _summarize_radio_value(value)
            return
        if command in RADIO_SET_COMMANDS:
            self._handle_radio_value(command, value)
            return
        if command in WEATHER_SET_COMMANDS:
            self._handle_weather_value(command, value)
            return
        if command in WEATHER_ASSIGN_COMMANDS:
            self._last_app_values[command] = _summarize_weather_value(value)
            return
        if command in CONSUMPTION_COMMAND_IDS:
            self._handle_consumption_value(command, value)
            return
        if command == LAST_USAGE_SET_COMMAND:
            self._handle_last_usage_value(value)
            return
        if command in SAVING_MONITOR_COMMAND_IDS:
            self._handle_saving_monitor_value(command, value)
            return
        if command in {TEMP_MEMORY_SET_COMMAND, TEMP_MEMORY_ASSIGN_COMMAND}:
            self._handle_temperature_memory_value(value, source_command=command)
            return
        if command in DEVICE_INFO_COMMAND_IDS:
            self._handle_device_info_value(command, value)
            return
        if command in {CURRENCY_GET_COMMAND, CURRENCY_SET_COMMAND}:
            self._handle_currency_value(value, source_command=command)
            return
        if command in APP_STARTUP_SET_COMMANDS:
            self._handle_app_startup_value(command, value)
            return
        if is_radio_command:
            _LOGGER.debug(
                "DHE radio unhandled command=%s value_summary=%r",
                command,
                _summarize_radio_value(value),
            )
            return
        if command not in {ODB_SET_COMMAND, ODB_ASSIGN_COMMAND}:
            self._log_unhandled_ste_command(command, value)
            return
        if not isinstance(value, dict):
            self._log_unhandled_ste_command(command, value)
            return
        try:
            odb_id = int(value.get("id", -1))
        except (TypeError, ValueError):
            self._log_unhandled_ste_command(command, value)
            return
        source = self._odb_read_source(command, odb_id)
        self._handle_odb_value(
            odb_id,
            value.get("value"),
            is_valid=value.get("isValid"),
            source=source,
        )

    def _handle_radio_value(self, command: str, raw_value: Any) -> None:
        field = command.rsplit(":", 1)[-1]
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

    def _copy_diagnostic_state(self) -> dict[str, Any]:
        state = {
            key: _copy_json_like_value(value)
            for key, value in self._diagnostic_state.items()
        }
        if self._last_message_monotonic is not None:
            state["last_message_age_seconds"] = max(
                0,
                round(time.monotonic() - self._last_message_monotonic),
            )
        return state

    def _update_diagnostics(self, **updates: Any) -> None:
        changed = False
        for key, value in updates.items():
            if value is None:
                if key in self._diagnostic_state:
                    self._diagnostic_state.pop(key)
                    changed = True
                continue
            if self._diagnostic_state.get(key) != value:
                self._diagnostic_state[key] = value
                changed = True
        if not changed:
            return
        state = self._copy_diagnostic_state()
        self._notify_callbacks("diagnostic", self._diagnostic_callbacks, state)

    def _record_runtime_message(self, command: Any, value: Any) -> None:
        if not isinstance(command, str):
            return
        self._last_message_monotonic = time.monotonic()
        self._message_count += 1
        self._update_diagnostics(
            last_message_command=command,
            last_message_received_at=_diagnostic_timestamp(),
            last_message_summary=_summarize_diagnostic_value(value),
            message_count=self._message_count,
        )

    def _handle_odb_setpoint_value(self, raw_value: Any) -> None:
        self._handle_setpoint(_raw_tenths_to_c(_raw_to_float(raw_value)))

    def _handle_odb_water_flow_value(self, raw_value: Any) -> None:
        self._handle_measurement(ID_WATER_FLOW, _raw_to_float(raw_value) / 10.0)

    def _handle_odb_power_percent_value(self, raw_value: Any) -> None:
        self._last_power_fraction = _raw_to_float(raw_value) / 100.0
        self._handle_measurement(
            ID_POWER_PERCENT,
            self._last_power_fraction * self._nominal_power_kw,
        )

    def _handle_odb_nominal_power_value(self, raw_value: Any) -> None:
        self._nominal_power_kw = self._raw_nominal_power_to_kw(_raw_to_float(raw_value))
        self._handle_measurement(ID_NOMINAL_POWER, self._nominal_power_kw)
        if self._last_power_fraction is not None:
            self._handle_measurement(
                ID_POWER_PERCENT,
                self._last_power_fraction * self._nominal_power_kw,
            )

    def _handle_odb_bath_fill_target_value(self, raw_value: Any) -> None:
        self._handle_measurement(
            ID_BATH_FILL_TARGET_VOLUME,
            self._convert_odb_value(ID_BATH_FILL_TARGET_VOLUME, raw_value),
        )
        self._refresh_bath_fill_remaining()

    def _handle_odb_bath_fill_current_value(self, raw_value: Any) -> None:
        self._handle_measurement(ID_BATH_FILL_CURRENT_VOLUME, max(0.0, _raw_to_float(raw_value)))
        self._refresh_bath_fill_remaining()

    def _handle_odb_protocol_version_value(self, raw_value: Any) -> None:
        self._handle_measurement(
            ID_PROTOCOL_VERSION,
            round(max(0.0, _raw_to_float(raw_value))),
        )

    def _handle_odb_water_heating_enabled_value(self, raw_value: Any) -> None:
        self._handle_measurement(ID_WATER_HEATING_ENABLED, _raw_to_water_heating_enabled(raw_value))

    def _handle_odb_scald_protection_active_value(self, raw_value: Any) -> None:
        self._handle_measurement(ID_SCALD_PROTECTION_ACTIVE, _raw_to_bool(raw_value))

    def _handle_odb_device_status_value(self, raw_value: Any) -> None:
        self._handle_device_status(raw_value)

    def _handle_odb_co2_emission_value(self, raw_value: Any) -> None:
        self._handle_co2_emission(raw_value)

    def _handle_odb_child_safety_active_value(self, raw_value: Any) -> None:
        self._handle_measurement(ID_CHILD_SAFETY_ACTIVE, _raw_to_bool(raw_value))

    def _handle_odb_value(
        self,
        odb_id: int,
        raw_value: Any,
        *,
        is_valid: Any = None,
        source: ODBReadSource = ODB_READ_SOURCE_RUNTIME,
    ) -> None:
        if is_valid is False:
            if int(odb_id) not in KNOWN_ODB_VALUE_IDS:
                self._log_unknown_odb_value(odb_id, raw_value, is_valid=False)
            return
        try:
            if (
                not _should_publish_odb_readback(
                    odb_id,
                    raw_value,
                    source=source,
                )
            ):
                return
            handler = self._odb_value_handlers.get(odb_id)
            if handler is not None:
                handler(raw_value)
                return
            if odb_id in ODB_TENTHS_TEMPERATURE_IDS:
                self._handle_measurement(odb_id, _raw_tenths_to_c(_raw_to_float(raw_value)))
                return
            if odb_id in ODB_NONNEGATIVE_VALUE_IDS:
                self._handle_measurement(odb_id, max(0.0, _raw_to_float(raw_value)))
                return
            if odb_id in ODB_DECILITER_VALUE_IDS:
                self._handle_measurement(odb_id, max(0.0, _raw_to_float(raw_value)) / 10.0)
                return
            if odb_id in PRICE_COMPONENT_IDS:
                self._handle_price_component(odb_id, raw_value)
                return
            if odb_id in ODB_IGNORED_VALUE_IDS:
                return
            if odb_id in WRITABLE_OPTION_IDS:
                self._handle_measurement(odb_id, self._convert_odb_value(odb_id, raw_value))
                return
            self._log_unknown_odb_value(odb_id, raw_value, is_valid=is_valid)
        except (TypeError, ValueError):
            return

    def _odb_read_source(self, command: Any, odb_id: int) -> ODBReadSource:
        """Classify an incoming ODB value as requested readback or runtime update."""
        if command == ODB_SET_COMMAND and self._consume_odb_read_request(odb_id):
            return ODB_READ_SOURCE_REQUESTED
        return ODB_READ_SOURCE_RUNTIME

    def _mark_odb_read_requested(self, odb_id: int) -> None:
        """Track zero-placeholder-sensitive reads until their first readback."""
        odb_id = int(odb_id)
        if odb_id not in ODB_ZERO_REQUEST_READBACK_IGNORE_IDS:
            return
        pending = getattr(self, "_pending_odb_read_deadlines", None)
        if pending is None:
            pending = self._pending_odb_read_deadlines = {}
        pending[odb_id] = time.monotonic() + ODB_READBACK_REQUEST_WINDOW_SECONDS

    def _consume_odb_read_request(self, odb_id: int) -> bool:
        """Return whether an ODB value is the readback for a recent request."""
        pending = getattr(self, "_pending_odb_read_deadlines", None)
        if pending is None:
            return False
        deadline = pending.pop(int(odb_id), None)
        return deadline is not None and deadline >= time.monotonic()

    def _log_unhandled_ste_command(self, command: Any, value: Any) -> None:
        if not isinstance(command, str) or not command.startswith(
            ("get:ste", "set:ste", "assign:ste")
        ):
            return
        _LOGGER.debug(
            "Unhandled DHE ste command=%s value_summary=%r",
            command,
            _summarize_diagnostic_value(value),
        )

    def _refresh_bath_fill_remaining(self) -> None:
        target = self._last_measurements.get(ID_BATH_FILL_TARGET_VOLUME)
        current = self._last_measurements.get(ID_BATH_FILL_CURRENT_VOLUME)
        if target is None or current is None:
            return
        try:
            target_l = max(0.0, _raw_to_float(target))
            current_l = max(0.0, _raw_to_float(current))
        except (TypeError, ValueError):
            return

        attributes = {
            "source": "derived",
            "target_l": target_l,
            "filled_l": current_l,
            "target_odb_id": ID_BATH_FILL_TARGET_VOLUME,
            "filled_odb_id": ID_BATH_FILL_CURRENT_VOLUME,
        }
        previous_attributes = self._last_measurement_attributes.get(ID_BATH_FILL_REMAINING_VOLUME)
        self._last_measurement_attributes[ID_BATH_FILL_REMAINING_VOLUME] = attributes
        self._handle_measurement(
            ID_BATH_FILL_REMAINING_VOLUME,
            round(max(target_l - current_l, 0.0)),
            force_update=previous_attributes != attributes,
        )

    def _handle_price_component(self, odb_id: int, raw_value: Any) -> None:
        value = round(_raw_to_float(raw_value))
        measurement_id, euros_odb_id, cents_odb_id = PRICE_COMPONENT_IDS[odb_id]
        if odb_id == cents_odb_id:
            value = int(_clamp(value, 0, PRICE_CENTS_COMPONENT_MAX))
        else:
            max_euros = PRICE_EUROS_COMPONENT_MAX_BY_ID.get(euros_odb_id, 9)
            value = int(_clamp(value, 0, max_euros))
        self._handle_measurement(odb_id, float(value))

        euros_value = self._last_measurements.get(euros_odb_id)
        cents_value = self._last_measurements.get(cents_odb_id)
        if euros_value is None or cents_value is None:
            return
        price = float(int(euros_value)) + (float(int(cents_value)) / 100.0)
        attributes = {
            "source_odb_ids": {
                "euros": euros_odb_id,
                "cents": cents_odb_id,
            },
            "euros": int(euros_value),
            "cents": int(cents_value),
        }
        previous_attributes = self._last_measurement_attributes.get(measurement_id)
        self._last_measurement_attributes[measurement_id] = attributes
        self._handle_measurement(
            measurement_id,
            price,
            force_update=previous_attributes != attributes,
        )

    def _handle_co2_emission(self, raw_value: Any) -> None:
        raw = _raw_to_float(raw_value)
        value = self._raw_to_co2_emission(raw)
        self._handle_measurement(ID_CO2_EMISSION_RAW, raw)
        attributes = {
            "source_odb_id": ID_CO2_EMISSION_RAW,
            "raw_value": raw,
        }
        previous_attributes = self._last_measurement_attributes.get(ID_CO2_EMISSION)
        self._last_measurement_attributes[ID_CO2_EMISSION] = attributes
        self._handle_measurement(
            ID_CO2_EMISSION,
            value,
            force_update=previous_attributes != attributes,
        )

    def _handle_device_status(self, raw_value: Any) -> None:
        raw = int(_raw_to_float(raw_value))
        status = _device_status_key(raw)
        attributes = {
            "raw_value": raw,
            "status": status,
            "service_required": _device_status_problem(raw),
        }
        previous_attributes = self._last_measurement_attributes.get(ID_DEVICE_STATUS)
        self._last_measurement_attributes[ID_DEVICE_STATUS] = attributes
        self._handle_measurement(
            ID_DEVICE_STATUS,
            status,
            force_update=previous_attributes != attributes,
        )

    @staticmethod
    def _co2_emission_to_raw(kg_per_kwh: float) -> int:
        return round(float(kg_per_kwh) * 1000)

    @staticmethod
    def _raw_to_co2_emission(raw_value: float) -> float:
        return round(_clamp(float(raw_value), 0.0, CO2_EMISSION_RAW_MAX) / 1000.0, 3)

    @staticmethod
    def _odb_debug_name(odb_id: Any) -> str:
        try:
            return ODB_DEBUG_NAMES.get(int(odb_id), "unknown")
        except (TypeError, ValueError):
            return "unknown"

    @staticmethod
    def _log_unknown_odb_value(odb_id: int, raw_value: Any, *, is_valid: Any = None) -> None:
        _LOGGER.debug(
            "Unknown DHE ODB value id=%s name=%s value=%r is_valid=%r",
            odb_id,
            DHEClientRuntimeMixin._odb_debug_name(odb_id),
            raw_value,
            is_valid,
        )

    def _handle_setpoint(self, value: float) -> None:
        previous = self._last_setpoint
        self._last_setpoint = value
        if previous is None or abs(previous - value) >= 0.01:
            self._notify_callbacks("setpoint", self._setpoint_callbacks, value)
        future = self._pending_setpoint_future
        expected = self._pending_expected_setpoint
        if future is not None and not future.done() and (expected is None or abs(value - expected) < 0.01):
            future.set_result(value)
            self._pending_setpoint_future = None
            self._pending_expected_setpoint = None

    def _handle_measurement(self, odb_id: int, value: MeasurementValue, *, force_update: bool = False) -> None:
        previous = self._last_measurements.get(odb_id, _MISSING_MEASUREMENT)
        self._last_measurements[odb_id] = value
        if value is not None and not isinstance(value, str):
            self._maybe_complete_write_future(odb_id, value)
        if not force_update and previous is not _MISSING_MEASUREMENT:
            if isinstance(previous, str) or isinstance(value, str):
                if previous == value:
                    return
            elif _values_equal(previous, value):
                return
        self._notify_callbacks(
            "measurement",
            self._measurement_callbacks,
            odb_id,
            value,
        )

    def _maybe_complete_write_future(self, odb_id: int, value: ODBValue) -> None:
        future = self._pending_write_future
        if future is None or future.done() or self._pending_write_id != odb_id:
            return
        expected = self._pending_write_expected
        if expected is None or _values_equal(value, expected):
            future.set_result(value)
            self._pending_write_future = None
            self._pending_write_id = None
            self._pending_write_expected = None

    async def _wait_for_setpoint_confirmation(
        self,
        ctx: DHESession,
        future: asyncio.Future[float],
    ) -> float:
        deadline = time.monotonic() + COMMAND_CONFIRMATION_TIMEOUT
        next_readback = 0.0
        while not future.done():
            now = time.monotonic()
            if now >= deadline:
                break
            if now >= next_readback:
                await self._request_setpoint(ctx)
                next_readback = now + COMMAND_READBACK_INTERVAL
            timeout = min(COMMAND_READBACK_INTERVAL, max(0.1, deadline - now))
            try:
                return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
            except TimeoutError:
                continue
        if future.done():
            return future.result()
        raise DHEError("setpoint confirmation timed out")

    async def _wait_for_write_confirmation(
        self,
        ctx: DHESession,
        future: asyncio.Future[ODBValue],
        odb_id: int,
    ) -> ODBValue:
        deadline = time.monotonic() + COMMAND_CONFIRMATION_TIMEOUT
        next_readback = 0.0
        while not future.done():
            now = time.monotonic()
            if now >= deadline:
                break
            if now >= next_readback:
                await self._request_odb_value(ctx, odb_id)
                next_readback = now + COMMAND_READBACK_INTERVAL
            timeout = min(COMMAND_READBACK_INTERVAL, max(0.1, deadline - now))
            try:
                return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
            except TimeoutError:
                continue
        if future.done():
            return future.result()
        raise DHEError(f"write confirmation timed out for DHE ODB id {odb_id}")

    async def _wait_for_app_write_confirmation(
        self,
        future: asyncio.Future[ODBValue],
    ) -> ODBValue:
        return await asyncio.wait_for(
            asyncio.shield(future),
            timeout=APP_COMMAND_CONFIRMATION_TIMEOUT,
        )

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
                and str(self._last_weather_state["location"].get("LocationId", "")) == location_id
            ),
            timeout_seconds=APP_COMMAND_CONFIRMATION_TIMEOUT,
        ):
            return
        raise DHEError("weather location selection timed out")

    @staticmethod
    def _convert_odb_value(odb_id: int, raw_value: Any) -> ODBValue:
        if odb_id in {ID_BATH_FILL_ACTIVE, ID_CHILD_SAFETY_ACTIVE, ID_ECO_MODE, ID_WELLNESS_ACTIVE}:
            return _raw_to_bool(raw_value)
        if odb_id == ID_WATER_HEATING_ENABLED:
            return _raw_to_water_heating_enabled(raw_value)
        if odb_id == ID_CHILD_SAFETY_TEMPERATURE_LIMIT:
            value = _raw_to_float(raw_value)
            if 200.0 <= value <= 600.0:
                return _raw_tenths_to_c(value)
            return value
        if odb_id == ID_ECO_FLOW_LIMIT:
            value = _raw_to_float(raw_value)
            if 40.0 <= value <= 150.0:
                return value / 10.0
            return value
        return _raw_to_float(raw_value)

    @staticmethod
    def _raw_nominal_power_to_kw(raw: int | float) -> float:
        value = float(raw)
        if 12.0 <= value <= 36.0:
            return value
        if 120.0 <= value <= 360.0:
            return value / 10.0
        if 1200.0 <= value <= 3600.0:
            return value / 100.0
        _LOGGER.warning("Ignoring unexpected nominal DHE power value from ODB id 20: %s", raw)
        return DEFAULT_NOMINAL_POWER_KW
