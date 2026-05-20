"""App-level runtime value handlers for the DHE client."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any

from .client_types import MeasurementCallback, MeasurementValue
from .device_info_helpers import product_id_prefix as _product_id_prefix

from .client_value_helpers import (
    raw_to_bool as _raw_to_bool,
    raw_to_float as _raw_to_float,
)
from .protocol import (
    APP_SETTING_SET_COMMAND_IDS,
    BRUSH_TIMER_PATH,
    CONSUMPTION_COMMAND_IDS,
    DEFAULT_TEMPERATURE_MEMORY_NAMES,
    DEVICE_INFO_SET_COMMANDS,
    ID_APP_CURRENCY,
    ID_BRUSH_TIMER_ACTIVATION,
    ID_BRUSH_TIMER_DURATION,
    ID_BRUSH_TIMER_REMAINING,
    ID_DEVICE_INFO,
    ID_LAST_USAGE_COST,
    ID_LAST_USAGE_ENERGY,
    ID_LAST_USAGE_TIME,
    ID_LAST_USAGE_WATER,
    ID_SAVING_MONITOR_ACTIVATION_RATE,
    ID_SHOWER_TIMER_ACTIVATION,
    ID_SHOWER_TIMER_DURATION,
    ID_SHOWER_TIMER_REMAINING,
    LAST_USAGE_SET_COMMAND,
    SAVING_MONITOR_SENSOR_FIELDS,
    SHOWER_TIMER_PATH,
    TEMPERATURE_MEMORY_ID_TO_MEASUREMENT,
    TIMER_DEFAULT_DURATIONS,
    TIMER_PATH_IDS,
    WELLNESS_PROGRAMS_SET_COMMAND,
)
from .wellness_programs import normalize_wellness_programs as _normalize_wellness_programs


def _update_optional_device_text(
    device_info: dict[str, Any],
    key: str,
    raw_value: Any,
) -> None:
    if raw_value is None:
        device_info.pop(key, None)
        return
    text = str(raw_value).strip()
    if text:
        device_info[key] = text
        return
    device_info.pop(key, None)


class DHEClientRuntimeAppMixin:
    """Handle app, saving monitor and device-info runtime values."""

    if TYPE_CHECKING:
        _last_app_values: dict[str, Any]
        _last_device_info: dict[str, Any]
        _last_measurement_attributes: dict[int, dict[str, Any]]
        _last_measurements: dict[int, MeasurementValue]
        _last_saving_monitor_values: dict[str, Any]
        _last_wellness_programs: tuple[dict[str, Any], ...]
        _measurement_callbacks: set[MeasurementCallback]
        _temperature_memory_full_list_seen: bool
        _temperature_memory_generation: int
        _temperature_memory_ids_seen: set[int]
        _wellness_program_callbacks: set[Callable[[tuple[dict[str, Any], ...]], None]]

        def _handle_measurement(
            self,
            odb_id: int,
            value: MeasurementValue,
            *,
            force_update: bool = False,
        ) -> None: ...

        def _notify_callbacks(
            self,
            callback_name: str,
            callbacks: set[Callable[..., None]],
            *args: Any,
        ) -> None: ...

    def _handle_app_timer_value(self, command: str, raw_value: Any) -> None:
        try:
            _action, path, property_name = command.split(":", 2)
            measurement_id = TIMER_PATH_IDS.get(path, {}).get(property_name)
            if measurement_id is None:
                return
            if property_name == "activation":
                self._handle_measurement(measurement_id, _raw_to_bool(raw_value))
            elif property_name == "durationMilliseconds":
                minutes = _raw_to_float(raw_value) / 60000.0
                self._handle_measurement(measurement_id, minutes)
                remaining_id = TIMER_PATH_IDS[path]["remainingMilliseconds"]
                self._handle_measurement(remaining_id, minutes, force_update=True)
            elif property_name == "remainingMilliseconds":
                self._handle_measurement(
                    measurement_id, _raw_to_float(raw_value) / 60000.0
                )
        except (TypeError, ValueError):
            return

    def _handle_app_timer_reset(self, command: str) -> None:
        try:
            _action, path, _property_name = command.split(":", 2)
        except ValueError:
            return
        if path == BRUSH_TIMER_PATH:
            self._handle_measurement(
                ID_BRUSH_TIMER_REMAINING,
                self._app_timer_duration_minutes(
                    ID_BRUSH_TIMER_DURATION,
                    BRUSH_TIMER_PATH,
                ),
                force_update=True,
            )
            self._handle_measurement(
                ID_BRUSH_TIMER_ACTIVATION, False, force_update=True
            )
        elif path == SHOWER_TIMER_PATH:
            self._handle_measurement(
                ID_SHOWER_TIMER_REMAINING,
                self._app_timer_duration_minutes(
                    ID_SHOWER_TIMER_DURATION,
                    SHOWER_TIMER_PATH,
                ),
                force_update=True,
            )
            self._handle_measurement(
                ID_SHOWER_TIMER_ACTIVATION, False, force_update=True
            )

    def _app_timer_duration_minutes(
        self,
        duration_id: int,
        path: str,
    ) -> float:
        """Return the configured timer duration in minutes."""
        value = self._last_measurements.get(duration_id)
        try:
            duration = _raw_to_float(value)
        except (TypeError, ValueError):
            duration = TIMER_DEFAULT_DURATIONS[path]
        return max(0.0, duration)

    def _handle_consumption_value(self, command: str, raw_value: Any) -> None:
        if not isinstance(raw_value, dict):
            return
        measurement_id = CONSUMPTION_COMMAND_IDS[command]
        raw_chart = raw_value.get("chart", [])
        if not isinstance(raw_chart, list):
            return
        try:
            chart = [_raw_to_float(value) for value in raw_chart]
            cost_eur = (
                _raw_to_float(raw_value["sum"])
                if raw_value.get("sum") is not None
                else None
            )
        except (TypeError, ValueError):
            return

        attributes = {
            "chart": chart,
            "cost_eur": cost_eur,
            "source_command": command,
        }
        previous_attributes = self._last_measurement_attributes.get(measurement_id)
        self._last_measurement_attributes[measurement_id] = attributes
        self._handle_measurement(
            measurement_id,
            sum(chart),
            force_update=previous_attributes != attributes,
        )

    def _handle_last_usage_value(self, raw_value: Any) -> None:
        if not isinstance(raw_value, dict):
            return

        fields = {
            "water": ID_LAST_USAGE_WATER,
            "energy": ID_LAST_USAGE_ENERGY,
            "time": ID_LAST_USAGE_TIME,
            "costs": ID_LAST_USAGE_COST,
        }
        for field, measurement_id in fields.items():
            item = raw_value.get(field)
            if not isinstance(item, dict):
                continue
            try:
                value = _raw_to_float(item.get("value"))
            except (TypeError, ValueError):
                continue
            if field in {"water", "energy"}:
                value = round(value, 2)

            attributes: dict[str, Any] = {
                "source_command": LAST_USAGE_SET_COMMAND,
                "last_usage_field": field,
            }
            for key in ("min", "max"):
                if item.get(key) is None:
                    continue
                try:
                    attributes[key] = _raw_to_float(item[key])
                except (TypeError, ValueError):
                    attributes[key] = item[key]

            previous_attributes = self._last_measurement_attributes.get(measurement_id)
            self._last_measurement_attributes[measurement_id] = attributes
            self._handle_measurement(
                measurement_id,
                value,
                force_update=previous_attributes != attributes,
            )

    def _handle_saving_monitor_value(self, command: str, raw_value: Any) -> None:
        key = command.rsplit(":", 1)[-1]
        if key == "ActivationRate":
            try:
                activation_rate = round(_raw_to_float(raw_value), 1)
            except (TypeError, ValueError):
                return
            self._last_saving_monitor_values["activation_rate"] = activation_rate
            self._update_saving_monitor_sensor(
                ID_SAVING_MONITOR_ACTIVATION_RATE,
                activation_rate,
                "activation_rate",
                "activation_rate",
            )
            return

        if not isinstance(raw_value, dict):
            return
        try:
            values = {
                "water_l": round(_raw_to_float(raw_value["water_l"]), 2),
                "energy_kwh": round(_raw_to_float(raw_value["energy_Wh"]) / 1000.0, 2),
                "co2_kg": round(_raw_to_float(raw_value["emission_Co2Kg"]), 2),
            }
            if raw_value.get("value_E") is not None:
                values["value_eur"] = round(_raw_to_float(raw_value["value_E"]), 2)
        except (KeyError, TypeError, ValueError):
            return

        category = key.lower()
        self._last_saving_monitor_values[category] = values
        self._refresh_saving_monitor_sensors(category=category)

    def _refresh_saving_monitor_sensors(self, *, category: str | None = None) -> None:
        field_groups: Iterable[tuple[str, dict[str, int]]]
        if category is None:
            field_groups = SAVING_MONITOR_SENSOR_FIELDS.items()
        else:
            field_ids = SAVING_MONITOR_SENSOR_FIELDS.get(category)
            if field_ids is None:
                return
            field_groups = ((category, field_ids),)

        for category, field_ids in field_groups:
            values = self._last_saving_monitor_values.get(category)
            if not isinstance(values, dict):
                continue
            for field, measurement_id in field_ids.items():
                value = values.get(field)
                if value is not None:
                    self._update_saving_monitor_sensor(
                        measurement_id, value, category, field
                    )

    def _update_saving_monitor_sensor(
        self,
        measurement_id: int,
        value: float,
        category: str,
        field: str,
    ) -> None:
        command_category = (
            "ActivationRate" if category == "activation_rate" else category
        )
        source_command = f"set:ste.app.savingMonitor:{command_category}"
        attributes: dict[str, Any] = {
            "source_command": source_command,
            "saving_monitor_category": category,
            "saving_monitor_field": field,
        }
        stored_value = self._last_saving_monitor_values.get(category)
        if stored_value is not None:
            attributes[category] = stored_value

        previous_attributes = self._last_measurement_attributes.get(measurement_id)
        self._last_measurement_attributes[measurement_id] = attributes
        self._handle_measurement(
            measurement_id,
            value,
            force_update=previous_attributes != attributes,
        )

    def _handle_app_startup_value(self, command: str, raw_value: Any) -> None:
        if command == WELLNESS_PROGRAMS_SET_COMMAND:
            self._handle_wellness_programs_value(raw_value, source_command=command)
            return

        self._last_app_values[command] = raw_value
        measurement_id = APP_SETTING_SET_COMMAND_IDS.get(command)
        if measurement_id is None:
            return

        attributes = {
            "source_command": command,
            "raw_value": raw_value,
        }
        previous_attributes = self._last_measurement_attributes.get(measurement_id)
        self._last_measurement_attributes[measurement_id] = attributes
        self._handle_measurement(
            measurement_id,
            self._format_app_setting_value(raw_value),
            force_update=previous_attributes != attributes,
        )

    def _handle_currency_value(self, raw_value: Any, *, source_command: str) -> None:
        if raw_value in (None, ""):
            return
        value = str(raw_value).strip().upper()
        if not value or value == "UNSET":
            return

        self._last_app_values[source_command] = raw_value
        attributes = {
            "source_command": source_command,
            "raw_value": raw_value,
        }
        previous_attributes = self._last_measurement_attributes.get(ID_APP_CURRENCY)
        self._last_measurement_attributes[ID_APP_CURRENCY] = attributes
        self._handle_measurement(
            ID_APP_CURRENCY,
            value,
            force_update=previous_attributes != attributes,
        )

    @staticmethod
    def _format_app_setting_value(raw_value: Any) -> str:
        if raw_value in (None, ""):
            return "unset"
        if isinstance(raw_value, bool):
            return "on" if raw_value else "off"
        if isinstance(raw_value, (dict, list)):
            return json.dumps(raw_value, sort_keys=True)
        return str(raw_value)

    def _handle_wellness_programs_value(
        self,
        raw_value: Any,
        *,
        source_command: str,
    ) -> None:
        programs = _normalize_wellness_programs(raw_value)
        if not programs:
            return

        self._last_app_values[source_command] = [dict(program) for program in programs]
        if programs == self._last_wellness_programs:
            return
        self._last_wellness_programs = programs
        self._notify_callbacks(
            "wellness_programs",
            self._wellness_program_callbacks,
            tuple(dict(program) for program in programs),
        )

    def _handle_device_info_value(self, command: str, raw_value: Any) -> None:
        self._last_app_values[command] = raw_value
        key = command.rsplit(":", 1)[-1]
        if key == "gadgetData" and isinstance(raw_value, dict):
            device_id = self._nested_value(raw_value, "id")
            if prefix := _product_id_prefix(device_id):
                self._last_device_info["product_id_prefix"] = prefix
            else:
                self._last_device_info.pop("product_id_prefix", None)
            self._last_device_info.update(
                {
                    "device_type": self._nested_value(raw_value, "type"),
                    "device_id": device_id,
                    "wlan_mac": self._nested_value(raw_value, "wlan"),
                    "bluetooth_mac": self._nested_value(raw_value, "bluetooth"),
                }
            )
        elif key == "controlunitName":
            _update_optional_device_text(
                self._last_device_info,
                "controlunit_name",
                raw_value,
            )
        elif key == "gadgetDataValid":
            try:
                self._last_device_info["gadget_data_valid"] = _raw_to_bool(raw_value)
            except (TypeError, ValueError):
                self._last_device_info["gadget_data_valid"] = bool(raw_value)
        elif key == "orderNumber":
            _update_optional_device_text(
                self._last_device_info,
                "order_number",
                raw_value,
            )
        elif key == "contactData" and isinstance(raw_value, dict):
            self._last_device_info["service_contact"] = {
                contact_key: self._nested_value(raw_value, contact_key)
                for contact_key in ("company", "mail", "phone")
            }
        else:
            self._last_device_info[key] = raw_value

        self._publish_device_info_measurement()

    def _publish_device_info_measurement(self) -> None:
        """Publish the combined device-info pseudo measurement."""
        state = str(
            self._last_device_info.get("device_type")
            or self._last_device_info.get("controlunit_name")
            or "DHE Connect"
        )
        attributes = {
            key: value
            for key, value in self._last_device_info.items()
            if value not in (None, "")
        }
        attributes["source_commands"] = list(DEVICE_INFO_SET_COMMANDS)
        previous_attributes = self._last_measurement_attributes.get(ID_DEVICE_INFO)
        self._last_measurement_attributes[ID_DEVICE_INFO] = attributes
        self._handle_measurement(
            ID_DEVICE_INFO,
            state,
            force_update=previous_attributes != attributes,
        )

    @staticmethod
    def _nested_value(raw_value: dict[str, Any], key: str) -> Any:
        value = raw_value.get(key)
        if isinstance(value, dict) and "value" in value:
            return value["value"]
        return value

    def _handle_temperature_memory_value(
        self, raw_value: Any, *, source_command: str
    ) -> None:
        if isinstance(raw_value, dict):
            if str(raw_value.get("operation", "")).lower() == "delete":
                self._handle_temperature_memory_delete_item(
                    raw_value, source_command=source_command
                )
                self._temperature_memory_generation += 1
                return
            memory_id = self._handle_temperature_memory_item(
                raw_value, source_command=source_command
            )
            if memory_id is not None:
                self._temperature_memory_ids_seen.add(memory_id)
                self._temperature_memory_generation += 1
            return
        if not isinstance(raw_value, list):
            return

        memory_ids: set[int] = set()
        for item in raw_value:
            memory_id = self._handle_temperature_memory_item(
                item, source_command=source_command
            )
            if memory_id is not None:
                memory_ids.add(memory_id)
        stale_memory_ids = self._temperature_memory_ids_seen - memory_ids
        if not self._temperature_memory_full_list_seen:
            stale_memory_ids = set(TEMPERATURE_MEMORY_ID_TO_MEASUREMENT) - memory_ids
        for stale_memory_id in stale_memory_ids:
            self._clear_temperature_memory(
                stale_memory_id, source_command=source_command
            )
        self._temperature_memory_ids_seen = memory_ids
        self._temperature_memory_full_list_seen = True
        self._temperature_memory_generation += 1

    def _handle_temperature_memory_delete_item(
        self, item: dict[str, Any], *, source_command: str
    ) -> None:
        raw_id = item.get("id")
        if raw_id is None:
            return
        try:
            memory_id = int(raw_id)
        except (TypeError, ValueError):
            return
        self._temperature_memory_ids_seen.discard(memory_id)
        self._clear_temperature_memory(memory_id, source_command=source_command)

    def _handle_temperature_memory_item(
        self, item: Any, *, source_command: str
    ) -> int | None:
        if not isinstance(item, dict):
            return None
        raw_id = item.get("id")
        if raw_id is None:
            return None
        try:
            memory_id = int(raw_id)
            temperature = _raw_to_float(item.get("temperature"))
        except (TypeError, ValueError):
            return None
        measurement_id = TEMPERATURE_MEMORY_ID_TO_MEASUREMENT.get(memory_id)
        if measurement_id is None:
            return None
        attributes = {
            "memory_id": memory_id,
            "name": str(
                item.get("name", DEFAULT_TEMPERATURE_MEMORY_NAMES.get(memory_id, ""))
            ),
            "source_command": source_command,
        }
        previous_attributes = self._last_measurement_attributes.get(measurement_id)
        self._last_measurement_attributes[measurement_id] = attributes
        self._handle_measurement(
            measurement_id,
            temperature,
            force_update=previous_attributes != attributes,
        )
        return memory_id

    def _clear_temperature_memory(self, memory_id: int, *, source_command: str) -> None:
        measurement_id = TEMPERATURE_MEMORY_ID_TO_MEASUREMENT.get(memory_id)
        if measurement_id is None:
            return
        self._last_measurements.pop(measurement_id, None)
        self._last_measurement_attributes[measurement_id] = {
            "memory_id": memory_id,
            "source_command": source_command,
            "operation": "delete",
        }
        self._notify_callbacks(
            "measurement",
            self._measurement_callbacks,
            measurement_id,
            None,
        )
