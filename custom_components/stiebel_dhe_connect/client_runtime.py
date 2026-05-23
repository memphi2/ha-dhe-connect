"""Runtime message handlers for the DHE client."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, cast

from .client_constants import (
    APP_COMMAND_CONFIRMATION_TIMEOUT,
    COMMAND_CONFIRMATION_TIMEOUT,
    COMMAND_READBACK_INTERVAL,
    DEFAULT_NOMINAL_POWER_KW,
    ODB_READBACK_REQUEST_WINDOW_SECONDS,
)
from .client_diagnostics import (
    diagnostic_timestamp as _diagnostic_timestamp,
    summarize_diagnostic_value as _summarize_diagnostic_value,
    summarize_radio_value as _summarize_radio_value,
    summarize_weather_value as _summarize_weather_value,
)
from .client_mapping import (
    copy_json_like_value as _copy_json_like_value,
    device_status_key as _device_status_key,
    device_status_problem as _device_status_problem,
)
from .client_runtime_app import DHEClientRuntimeAppMixin
from .client_runtime_media import DHEClientRuntimeMediaMixin
from .client_types import (
    DHEError,
    DHEEvent,
    DHESession,
    DHESessionClosed,
    DiagnosticCallback,
    MeasurementValue,
    ODB_READ_SOURCE_REQUESTED,
    ODB_READ_SOURCE_RUNTIME,
    ODBReadSource,
    ODBValue,
    MeasurementCallback,
    SetpointCallback,
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
from .protocol import (
    APP_STARTUP_SET_COMMANDS,
    APP_TIMER_RESET_COMMANDS,
    APP_TIMER_VALUE_COMMANDS,
    CO2_EMISSION_RAW_MAX,
    CONSUMPTION_COMMAND_IDS,
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
    LAST_USAGE_SET_COMMAND,
    ODB_ASSIGN_COMMAND,
    ODB_DEBUG_NAMES,
    ODB_DECILITER_VALUE_IDS,
    ODB_GET_COMMAND,
    ODB_IGNORED_VALUE_IDS,
    ODB_NONNEGATIVE_VALUE_IDS,
    ODB_SET_COMMAND,
    ODB_TENTHS_TEMPERATURE_IDS,
    ODB_VALUE_COMMANDS,
    ODB_ZERO_REQUEST_READBACK_IGNORE_IDS,
    PRICE_CENTS_COMPONENT_MAX,
    PRICE_COMPONENT_IDS,
    PRICE_EUROS_COMPONENT_MAX_BY_ID,
    RADIO_ASSIGN_COMMANDS,
    RADIO_FAVORITES_SET_COMMAND,
    RADIO_KNOWN_REQUEST_COMMANDS,
    RADIO_PATH,
    RADIO_SET_COMMANDS,
    RADIO_STATIONS_SET_COMMAND,
    SAVING_MONITOR_COMMAND_IDS,
    TEMPERATURE_MAX_OVERRIDE_COMMANDS,
    TEMP_MEMORY_ASSIGN_COMMAND,
    TEMP_MEMORY_SET_COMMAND,
    WEATHER_ASSIGN_COMMANDS,
    WEATHER_SET_COMMANDS,
    WRITABLE_OPTION_IDS,
    normalize_odb_command as _normalize_odb_command,
    normalize_odb_error_code as _normalize_odb_error_code,
    odb_error_name as _odb_error_name,
)

_LOGGER = logging.getLogger(__name__)
_MISSING_MEASUREMENT = object()
ODB_ERROR_FIELD_KEYS = ("error", "errorCode", "error_code", "odbError", "odb_error", "err")


def _extract_odb_error_code(value: Any) -> int | None:
    """Return an optional normalized DHE ODB error code from a payload."""
    if not isinstance(value, Mapping):
        return None
    for key in ODB_ERROR_FIELD_KEYS:
        if key not in value:
            continue
        try:
            return _normalize_odb_error_code(value[key])
        except ValueError:
            return None
    return None


class DHEClientRuntimeMixin(DHEClientRuntimeMediaMixin, DHEClientRuntimeAppMixin):
    """Runtime event dispatch, state updates and readback waiters."""

    if TYPE_CHECKING:
        _diagnostic_callbacks: set[DiagnosticCallback]
        _diagnostic_state: dict[str, Any]
        _last_app_values: dict[str, Any]
        _last_device_info: dict[str, Any]
        _last_measurement_attributes: dict[int, dict[str, Any]]
        _last_measurements: dict[int, MeasurementValue]
        _last_message_monotonic: float | None
        _last_power_fraction: float | None
        _last_setpoint: float | None
        _last_runtime_parser_category: str | None
        _measurement_callbacks: set[MeasurementCallback]
        _message_count: int
        _nominal_power_kw: float
        _odb_value_handlers: dict[int, Callable[..., None]]
        _ctx: DHESession | None
        _pending_expected_setpoint: float | None
        _pending_app_read_deadlines: dict[str, float]
        _pending_odb_read_deadlines: dict[int, float]
        _pending_setpoint_future: asyncio.Future[float] | None
        _pending_write_expected: ODBValue | None
        _pending_write_future: asyncio.Future[ODBValue] | None
        _pending_write_id: int | None
        _runtime_parser_stats: dict[str, int]
        _setpoint_callbacks: set[SetpointCallback]

        async def _request_setpoint(self, ctx: DHESession) -> None: ...

        async def _request_odb_value(self, ctx: DHESession, odb_id: int) -> None: ...

        def _publish_device_info_measurement(self) -> None: ...

        def _notify_callbacks(
            self,
            callback_name: str,
            callbacks: set[Callable[..., None]],
            *args: Any,
        ) -> None: ...

        def _create_background_task(self, coro: Any, name: str) -> asyncio.Task[Any]: ...

        async def _request_app_value(self, ctx: DHESession, command: str) -> None: ...

    async def _handle_runtime_event(self, event: DHEEvent) -> None:
        if event.name == "__closed":
            reason = (
                str(event.data)
                if isinstance(event.data, str) and event.data.strip()
                else "DHE closed Socket.IO session"
            )
            self._record_runtime_parser_category("socket_closed")
            self._update_diagnostics(
                connection_state="reconnecting",
                last_reconnect_reason=reason,
            )
            raise DHESessionClosed(reason)
        if event.name != "message":
            self._record_runtime_parser_category("ignored_event")
            return
        if not isinstance(event.data, dict):
            self._record_runtime_parser_category("invalid_message_payload")
            return
        data = event.data
        command = data.get("command")
        value = data.get("value")
        self._record_runtime_message(command, value)
        if not isinstance(command, str):
            self._record_runtime_parser_category("invalid_command")
            self._log_unhandled_ste_command(command, value)
            return
        is_radio_command = RADIO_PATH in command
        if command in APP_TIMER_RESET_COMMANDS:
            self._record_runtime_parser_category("timer_reset")
            self._handle_app_timer_reset(command)
            return
        if command in APP_TIMER_VALUE_COMMANDS:
            self._record_runtime_parser_category("timer_value")
            self._handle_app_timer_value(command, value)
            return
        if command in RADIO_KNOWN_REQUEST_COMMANDS:
            self._record_runtime_parser_category("radio_request")
            self._last_app_values[command] = _summarize_radio_value(value)
            return
        if command == RADIO_STATIONS_SET_COMMAND:
            self._record_runtime_parser_category("radio_stations")
            self._handle_radio_stations_value(value)
            return
        if command == RADIO_FAVORITES_SET_COMMAND:
            self._record_runtime_parser_category("radio_favorites")
            self._handle_radio_favorites_value(value)
            return
        if command in RADIO_ASSIGN_COMMANDS:
            self._record_runtime_parser_category("radio_assign")
            self._last_app_values[command] = _summarize_radio_value(value)
            return
        if command in RADIO_SET_COMMANDS:
            self._record_runtime_parser_category("radio_state")
            self._handle_radio_value(
                command,
                value,
                requested_readback=self._app_read_source(command),
            )
            return
        if command in WEATHER_SET_COMMANDS:
            self._record_runtime_parser_category("weather_state")
            self._handle_weather_value(command, value)
            return
        if command in WEATHER_ASSIGN_COMMANDS:
            self._record_runtime_parser_category("weather_assign")
            self._last_app_values[command] = _summarize_weather_value(value)
            return
        if command in CONSUMPTION_COMMAND_IDS:
            self._record_runtime_parser_category("consumption")
            self._handle_consumption_value(command, value)
            return
        if command == LAST_USAGE_SET_COMMAND:
            self._record_runtime_parser_category("last_usage")
            self._handle_last_usage_value(value)
            return
        if command in SAVING_MONITOR_COMMAND_IDS:
            self._record_runtime_parser_category("saving_monitor")
            self._handle_saving_monitor_value(command, value)
            return
        if command in {TEMP_MEMORY_SET_COMMAND, TEMP_MEMORY_ASSIGN_COMMAND}:
            self._record_runtime_parser_category("temperature_memory")
            self._handle_temperature_memory_value(value, source_command=command)
            return
        if command in TEMPERATURE_MAX_OVERRIDE_COMMANDS:
            self._record_runtime_parser_category("temperature_max_override")
            self._handle_temperature_max_override_value(command, value)
            return
        if command in DEVICE_INFO_COMMAND_IDS:
            self._record_runtime_parser_category("device_info")
            self._handle_device_info_value(command, value)
            return
        if command in APP_STARTUP_SET_COMMANDS:
            self._record_runtime_parser_category("app_startup")
            self._handle_app_startup_value(command, value)
            return
        if is_radio_command:
            self._record_runtime_parser_category("radio_unhandled")
            _LOGGER.debug(
                "DHE radio unhandled command=%s value_summary=%s",
                command,
                _summarize_radio_value(value),
            )
            return
        original_command = command
        if original_command in ODB_VALUE_COMMANDS and not isinstance(value, Mapping):
            self._record_runtime_parser_category("invalid_odb_payload")
            self._log_unhandled_ste_command(command, value)
            return
        try:
            normalized_odb_command = _normalize_odb_command(command, value)
        except ValueError:
            normalized_odb_command = None
        if normalized_odb_command is None:
            if original_command in ODB_VALUE_COMMANDS or original_command.startswith(
                ("get:ste.common.odb:", "set:ste.common.odb:", "assign:ste.common.odb:")
            ):
                self._record_runtime_parser_category("invalid_odb_id")
                self._log_unhandled_ste_command(command, value)
                return
            self._record_runtime_parser_category("unhandled")
            self._log_unhandled_ste_command(command, value)
            return
        command, odb_id = normalized_odb_command
        raw_value = value.get("value") if isinstance(value, Mapping) else value
        is_valid = value.get("isValid") if isinstance(value, Mapping) else None
        error_code = _extract_odb_error_code(value)
        self._record_runtime_parser_category("odb_value")
        source = self._odb_read_source(command, odb_id)
        self._handle_odb_value(
            odb_id,
            raw_value,
            is_valid=is_valid,
            error_code=error_code,
            source=source,
        )

    def _copy_diagnostic_state(self) -> dict[str, Any]:
        diagnostic_state = getattr(self, "_diagnostic_state", None)
        if not isinstance(diagnostic_state, dict):
            return {}
        state = {
            key: _copy_json_like_value(value)
            for key, value in diagnostic_state.items()
        }
        if self._last_message_monotonic is not None:
            state["last_message_age_seconds"] = max(
                0,
                round(time.monotonic() - self._last_message_monotonic),
            )
        return state

    def _update_diagnostics(self, **updates: Any) -> None:
        changed = False
        diagnostic_state = getattr(self, "_diagnostic_state", None)
        if not isinstance(diagnostic_state, dict):
            return
        for key, value in updates.items():
            if value is None:
                if key in diagnostic_state:
                    diagnostic_state.pop(key)
                    changed = True
                continue
            if diagnostic_state.get(key) != value:
                diagnostic_state[key] = value
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

    def _record_runtime_parser_category(self, category: str) -> None:
        self._last_runtime_parser_category = category
        # Keep one fast-path for normal operation, while tolerating unit-test
        # clients that instantiate the runtime mixin directly for targeted calls.
        stats = getattr(self, "_runtime_parser_stats", None)
        if not isinstance(stats, dict):
            stats = {}
            self._runtime_parser_stats = stats
        stats[category] = stats.get(category, 0) + 1

    def _handle_odb_setpoint_value(
        self,
        raw_value: Any,
        *,
        force_update: bool = False,
    ) -> None:
        self._handle_setpoint(_raw_tenths_to_c(_raw_to_float(raw_value)))

    def _handle_odb_water_flow_value(
        self,
        raw_value: Any,
        *,
        force_update: bool = False,
    ) -> None:
        self._handle_measurement(
            ID_WATER_FLOW,
            _raw_to_float(raw_value) / 10.0,
            force_update=force_update,
        )

    def _handle_odb_power_percent_value(
        self,
        raw_value: Any,
        *,
        force_update: bool = False,
    ) -> None:
        self._last_power_fraction = _raw_to_float(raw_value) / 100.0
        self._handle_measurement(
            ID_POWER_PERCENT,
            self._last_power_fraction * self._nominal_power_kw,
            force_update=force_update,
        )

    def _handle_odb_nominal_power_value(
        self,
        raw_value: Any,
        *,
        force_update: bool = False,
    ) -> None:
        self._nominal_power_kw = self._raw_nominal_power_to_kw(_raw_to_float(raw_value))
        self._handle_measurement(
            ID_NOMINAL_POWER,
            self._nominal_power_kw,
            force_update=force_update,
        )
        if self._last_power_fraction is not None:
            self._handle_measurement(
                ID_POWER_PERCENT,
                self._last_power_fraction * self._nominal_power_kw,
                force_update=force_update,
            )

    def _handle_odb_bath_fill_target_value(
        self,
        raw_value: Any,
        *,
        force_update: bool = False,
    ) -> None:
        self._handle_measurement(
            ID_BATH_FILL_TARGET_VOLUME,
            self._convert_odb_value(ID_BATH_FILL_TARGET_VOLUME, raw_value),
            force_update=force_update,
        )
        self._refresh_bath_fill_remaining()

    def _handle_odb_bath_fill_current_value(
        self,
        raw_value: Any,
        *,
        force_update: bool = False,
    ) -> None:
        self._handle_measurement(
            ID_BATH_FILL_CURRENT_VOLUME,
            max(0.0, _raw_to_float(raw_value)),
            force_update=force_update,
        )
        self._refresh_bath_fill_remaining()

    def _handle_odb_protocol_version_value(
        self,
        raw_value: Any,
        *,
        force_update: bool = False,
    ) -> None:
        self._last_device_info["raw_odb_protocol_version"] = round(
            max(0.0, _raw_to_float(raw_value)),
        )
        self._publish_device_info_measurement()
        protocol_version = self._last_device_info.get("protocol_version")
        if isinstance(protocol_version, str) and protocol_version:
            self._handle_measurement(
                ID_PROTOCOL_VERSION,
                protocol_version,
                force_update=force_update,
            )

    def _handle_odb_water_heating_enabled_value(
        self,
        raw_value: Any,
        *,
        force_update: bool = False,
    ) -> None:
        self._handle_measurement(
            ID_WATER_HEATING_ENABLED,
            _raw_to_water_heating_enabled(raw_value),
            force_update=force_update,
        )

    def _handle_odb_scald_protection_active_value(
        self,
        raw_value: Any,
        *,
        force_update: bool = False,
    ) -> None:
        self._handle_measurement(
            ID_SCALD_PROTECTION_ACTIVE,
            _raw_to_bool(raw_value),
            force_update=force_update,
        )

    def _handle_odb_device_status_value(
        self,
        raw_value: Any,
        *,
        force_update: bool = False,
    ) -> None:
        self._handle_device_status(raw_value, force_update=force_update)

    def _handle_odb_co2_emission_value(
        self,
        raw_value: Any,
        *,
        force_update: bool = False,
    ) -> None:
        self._handle_co2_emission(raw_value, force_update=force_update)

    def _handle_odb_child_safety_active_value(
        self,
        raw_value: Any,
        *,
        force_update: bool = False,
    ) -> None:
        child_safety_active = _raw_to_bool(raw_value)
        self._handle_measurement(
            ID_CHILD_SAFETY_ACTIVE,
            child_safety_active,
            force_update=force_update,
        )
        self._update_diagnostics(child_safety_active=child_safety_active)

    def _handle_odb_value(
        self,
        odb_id: int,
        raw_value: Any,
        *,
        is_valid: Any = None,
        error_code: int | None = None,
        source: ODBReadSource = ODB_READ_SOURCE_RUNTIME,
    ) -> None:
        if is_valid is False:
            self._record_invalid_odb_value(odb_id, raw_value, error_code=error_code)
            return
        try:
            if not _should_publish_odb_readback(
                odb_id,
                raw_value,
                source=source,
            ):
                return
            force_update = source == ODB_READ_SOURCE_REQUESTED
            handler = self._odb_value_handlers.get(odb_id)
            if handler is not None:
                handler(raw_value, force_update=force_update)
                return
            if odb_id in ODB_TENTHS_TEMPERATURE_IDS:
                self._handle_measurement(
                    odb_id,
                    _raw_tenths_to_c(_raw_to_float(raw_value)),
                    force_update=force_update,
                )
                return
            if odb_id in ODB_NONNEGATIVE_VALUE_IDS:
                self._handle_measurement(
                    odb_id,
                    max(0.0, _raw_to_float(raw_value)),
                    force_update=force_update,
                )
                return
            if odb_id in ODB_DECILITER_VALUE_IDS:
                self._handle_measurement(
                    odb_id,
                    max(0.0, _raw_to_float(raw_value)) / 10.0,
                    force_update=force_update,
                )
                return
            if odb_id in PRICE_COMPONENT_IDS:
                self._handle_price_component(
                    odb_id,
                    raw_value,
                    force_update=force_update,
                )
                return
            if odb_id in ODB_IGNORED_VALUE_IDS:
                return
            if odb_id in WRITABLE_OPTION_IDS:
                self._handle_measurement(
                    odb_id,
                    self._convert_odb_value(odb_id, raw_value),
                    force_update=force_update,
                )
                return
            self._log_unknown_odb_value(odb_id, raw_value, is_valid=is_valid)
        except (TypeError, ValueError):
            return

    def _record_invalid_odb_value(
        self,
        odb_id: int,
        raw_value: Any,
        *,
        error_code: int | None = None,
    ) -> None:
        """Record invalid ODB readback details for diagnostics only."""
        self._record_runtime_parser_category("invalid_odb_readback")
        odb_id = int(odb_id)
        error_name = _odb_error_name(error_code) if error_code is not None else None
        _LOGGER.debug(
            "Invalid DHE ODB value id=%s name=%s value=%s error_code=%s error_name=%s",
            odb_id,
            self._odb_debug_name(odb_id),
            _summarize_diagnostic_value(raw_value),
            error_code,
            error_name,
        )
        details: dict[str, Any] = {
            "id": odb_id,
            "name": self._odb_debug_name(odb_id),
            "value": _summarize_diagnostic_value(raw_value),
            "is_valid": False,
        }
        if error_code is not None:
            details["error_code"] = error_code
            details["error_name"] = _odb_error_name(error_code)
        self._update_diagnostics(
            last_invalid_odb=details,
            last_invalid_odb_at=_diagnostic_timestamp(),
        )

    def _odb_read_source(self, command: Any, odb_id: int) -> ODBReadSource:
        """Classify an incoming ODB value as requested readback or runtime update."""
        if command == ODB_GET_COMMAND and self._consume_odb_read_request(odb_id):
            return ODB_READ_SOURCE_REQUESTED
        if (
            command in {ODB_SET_COMMAND, ODB_ASSIGN_COMMAND}
            and odb_id not in ODB_ZERO_REQUEST_READBACK_IGNORE_IDS
            and self._consume_odb_read_request(odb_id)
        ):
            return ODB_READ_SOURCE_REQUESTED
        return ODB_READ_SOURCE_RUNTIME

    def _app_read_source(self, command: str) -> bool:
        """Return whether an app value is the readback for a recent request."""
        if self._consume_app_read_request(command):
            return True
        if command.startswith("set:") and self._consume_app_read_request(
            command.replace("set:", "get:", 1)
        ):
            return True
        return False

    def _mark_app_read_requested(self, command: str) -> None:
        """Track explicit app reads until their first readback."""
        self._pending_app_read_deadlines[str(command)] = (
            time.monotonic() + ODB_READBACK_REQUEST_WINDOW_SECONDS
        )

    def _consume_app_read_request(self, command: str) -> bool:
        """Return whether an app value is the readback for a recent request."""
        deadline = self._pending_app_read_deadlines.pop(str(command), None)
        return deadline is not None and deadline >= time.monotonic()

    def _mark_odb_read_requested(self, odb_id: int) -> None:
        """Track explicit ODB reads until their first readback."""
        odb_id = int(odb_id)
        self._pending_odb_read_deadlines[odb_id] = (
            time.monotonic() + ODB_READBACK_REQUEST_WINDOW_SECONDS
        )

    def _consume_odb_read_request(self, odb_id: int) -> bool:
        """Return whether an ODB value is the readback for a recent request."""
        deadline = self._pending_odb_read_deadlines.pop(int(odb_id), None)
        return deadline is not None and deadline >= time.monotonic()

    def _log_unhandled_ste_command(self, command: Any, value: Any) -> None:
        if not isinstance(command, str) or not command.startswith(
            ("get:ste", "set:ste", "assign:ste")
        ):
            return
        _LOGGER.debug(
            "Unhandled DHE ste command=%s value_summary=%s",
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
        previous_attributes = self._last_measurement_attributes.get(
            ID_BATH_FILL_REMAINING_VOLUME
        )
        self._last_measurement_attributes[ID_BATH_FILL_REMAINING_VOLUME] = attributes
        self._handle_measurement(
            ID_BATH_FILL_REMAINING_VOLUME,
            round(max(target_l - current_l, 0.0)),
            force_update=previous_attributes != attributes,
        )

    def _handle_price_component(
        self,
        odb_id: int,
        raw_value: Any,
        *,
        force_update: bool = False,
    ) -> None:
        value = round(_raw_to_float(raw_value))
        measurement_id, euros_odb_id, cents_odb_id = PRICE_COMPONENT_IDS[odb_id]
        if odb_id == cents_odb_id:
            value = int(_clamp(value, 0, PRICE_CENTS_COMPONENT_MAX))
        else:
            max_euros = PRICE_EUROS_COMPONENT_MAX_BY_ID.get(euros_odb_id, 9)
            value = int(_clamp(value, 0, max_euros))
        self._handle_measurement(odb_id, float(value), force_update=force_update)

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
            force_update=force_update or previous_attributes != attributes,
        )

    def _handle_co2_emission(
        self,
        raw_value: Any,
        *,
        force_update: bool = False,
    ) -> None:
        raw = _raw_to_float(raw_value)
        value = self._raw_to_co2_emission(raw)
        self._handle_measurement(
            ID_CO2_EMISSION_RAW,
            raw,
            force_update=force_update,
        )
        attributes = {
            "source_odb_id": ID_CO2_EMISSION_RAW,
            "raw_value": raw,
        }
        previous_attributes = self._last_measurement_attributes.get(ID_CO2_EMISSION)
        self._last_measurement_attributes[ID_CO2_EMISSION] = attributes
        self._handle_measurement(
            ID_CO2_EMISSION,
            value,
            force_update=force_update or previous_attributes != attributes,
        )

    def _handle_device_status(
        self,
        raw_value: Any,
        *,
        force_update: bool = False,
    ) -> None:
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
            force_update=force_update or previous_attributes != attributes,
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
    def _log_unknown_odb_value(
        odb_id: int, raw_value: Any, *, is_valid: Any = None
    ) -> None:
        _LOGGER.debug(
            "Unknown DHE ODB value id=%s name=%s value=%s is_valid=%r",
            odb_id,
            DHEClientRuntimeMixin._odb_debug_name(odb_id),
            _summarize_diagnostic_value(raw_value),
            is_valid,
        )

    def _handle_setpoint(self, value: float) -> None:
        previous = self._last_setpoint
        self._last_setpoint = value
        if previous is None or abs(previous - value) >= 0.01:
            self._notify_callbacks("setpoint", self._setpoint_callbacks, value)
        future = self._pending_setpoint_future
        expected = self._pending_expected_setpoint
        if (
            future is not None
            and not future.done()
            and (expected is None or abs(value - expected) < 0.01)
        ):
            future.set_result(value)
            self._pending_setpoint_future = None
            self._pending_expected_setpoint = None

    def _handle_measurement(
        self, odb_id: int, value: MeasurementValue, *, force_update: bool = False
    ) -> None:
        previous = self._last_measurements.get(odb_id, _MISSING_MEASUREMENT)
        self._last_measurements[odb_id] = value
        if value is not None and not isinstance(value, str):
            self._maybe_complete_write_future(odb_id, value)
        if not force_update and previous is not _MISSING_MEASUREMENT:
            previous_value = cast(MeasurementValue, previous)
            if isinstance(previous_value, str) or isinstance(value, str):
                if previous_value == value:
                    return
            elif _values_equal(previous_value, value):
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

    @staticmethod
    def _convert_odb_value(odb_id: int, raw_value: Any) -> ODBValue:
        if odb_id in {
            ID_BATH_FILL_ACTIVE,
            ID_CHILD_SAFETY_ACTIVE,
            ID_ECO_MODE,
            ID_WELLNESS_ACTIVE,
        }:
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
        _LOGGER.warning(
            "Ignoring unexpected nominal DHE power value from ODB id 20: %s", raw
        )
        return DEFAULT_NOMINAL_POWER_KW
