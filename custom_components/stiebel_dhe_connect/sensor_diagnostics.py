"""Diagnostic sensor entities for DHE Connect."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import callback
from homeassistant.helpers.entity import EntityCategory

from .client import DHEClient
from .client_mapping import DEVICE_STATUS_SERVICE_REQUIRED
from .client_types import MeasurementValue
from .entity_helpers import StiebelDHEEntityMixin
from .entity_state_helpers import coerce_float, connected_or_known_available
from .protocol import ID_DEVICE_STATUS, ID_INLET_TEMPERATURE


@dataclass(frozen=True, kw_only=True)
class StiebelDHEDiagnosticSensorEntityDescription(SensorEntityDescription):
    """Describe a DHE client diagnostic sensor."""

    diagnostic_key: str
    polls: bool = False


CONNECTION_STATE_OPTIONS = (
    "starting",
    "initializing",
    "connected",
    "reconnecting",
    "pairing_failed_waiting_manual_retry",
    "auth_failed",
    "stopping",
    "stopped",
)

ERROR_STATUS_OPTIONS = (
    "ok",
    "disconnected",
    "service_required",
    "target_below_inlet",
)
ERROR_STATUS_INLET_ATTRIBUTE_REFRESH_SECONDS = 120.0
DIAGNOSTIC_VOLATILE_ATTRIBUTE_KEYS = frozenset(
    {
        "last_message_age_seconds",
        "last_message_command",
        "last_message_received_at",
        "last_message_summary",
        "last_invalid_odb",
        "last_invalid_odb_at",
        "message_count",
        "next_reconnect_delay_seconds",
    }
)


DIAGNOSTIC_SENSOR_DESCRIPTIONS: tuple[StiebelDHEDiagnosticSensorEntityDescription, ...] = (
    StiebelDHEDiagnosticSensorEntityDescription(
        key="connection_state",
        translation_key="connection_state",
        icon="mdi:lan-connect",
        device_class=SensorDeviceClass.ENUM,
        options=CONNECTION_STATE_OPTIONS,
        diagnostic_key="connection_state",
    ),
    StiebelDHEDiagnosticSensorEntityDescription(
        key="last_reconnect_reason",
        translation_key="last_reconnect_reason",
        icon="mdi:alert-circle-outline",
        diagnostic_key="last_reconnect_reason",
    ),
    StiebelDHEDiagnosticSensorEntityDescription(
        key="next_reconnect_delay",
        translation_key="next_reconnect_delay",
        icon="mdi:timer-sync-outline",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        diagnostic_key="next_reconnect_delay_seconds",
    ),
)


class StiebelDHEReconnectCountSensor(StiebelDHEEntityMixin, SensorEntity):
    """DHE reconnect count diagnostic sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_icon = "mdi:restart"
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_translation_key = "reconnect_count"

    def __init__(self, entry_id: str, name: str, client: DHEClient) -> None:
        """Initialize the reconnect count sensor."""
        self._init_dhe_entity(
            entry_id=entry_id,
            key="reconnect_count",
            name=name,
            client=client,
        )
        self._attr_available = True
        self._attr_native_value = client.reconnect_count

    async def async_added_to_hass(self) -> None:
        """Subscribe to DHE reconnect updates and start the persistent session."""
        self.async_on_remove(
            self._client.add_reconnect_callback(self._handle_reconnect_update)
        )
        self._attr_native_value = self._client.reconnect_count

    @callback
    def _handle_reconnect_update(self, reconnect_count: int) -> None:
        """Handle DHE reconnect count updates."""
        self._attr_native_value = reconnect_count
        self.async_write_ha_state()


class StiebelDHEErrorStatusSensor(StiebelDHEEntityMixin, SensorEntity):
    """Human-readable general error status."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "error_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ERROR_STATUS_OPTIONS
    _attr_icon = "mdi:alert-octagon-outline"
    _unrecorded_attributes = frozenset({
        "inlet_temperature",
        "inlet_minus_setpoint",
    })

    def __init__(self, entry_id: str, name: str, client: DHEClient) -> None:
        """Initialize the general error status sensor."""
        self._init_dhe_entity(
            entry_id=entry_id,
            key="error_status",
            name=name,
            client=client,
        )
        self._setpoint: float | None = None
        self._inlet_temperature: float | None = None
        self._device_status: str | None = None
        self._attr_available = False
        self._attr_native_value: str | None = None
        self._last_written_status_signature: tuple[Any, ...] | None = None
        self._last_inlet_attribute_write_monotonic: float | None = None
        self._update_status()

    async def async_added_to_hass(self) -> None:
        """Subscribe to relevant DHE updates."""
        self.async_on_remove(
            self._client.add_setpoint_callback(self._handle_setpoint_update)
        )
        self.async_on_remove(
            self._client.add_measurement_callback(self._handle_measurement_update)
        )
        self.async_on_remove(
            self._client.add_availability_callback(self._handle_availability_update)
        )
        self._setpoint = self._coerce_temperature(self._client.last_setpoint)
        self._inlet_temperature = self._coerce_temperature(
            self._client.last_measurements.get(ID_INLET_TEMPERATURE)
        )
        device_status = self._client.last_measurements.get(ID_DEVICE_STATUS)
        self._device_status = str(device_status) if isinstance(device_status, str) else None
        self._update_status()
        self._write_status_state(force=True)

    @callback
    def _handle_setpoint_update(self, value: float) -> None:
        self._setpoint = self._coerce_temperature(value)
        self._update_status()
        self._write_status_state()

    @callback
    def _handle_measurement_update(self, odb_id: int, value: MeasurementValue) -> None:
        inlet_update = odb_id == ID_INLET_TEMPERATURE
        if odb_id == ID_INLET_TEMPERATURE:
            self._inlet_temperature = self._coerce_temperature(value)
        elif odb_id == ID_DEVICE_STATUS:
            self._device_status = str(value) if isinstance(value, str) else None
        else:
            return
        self._update_status()
        self._write_status_state(
            force=inlet_update and self._should_refresh_inlet_attributes()
        )

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        self._attr_available = connected_or_known_available(
            available,
            self._setpoint,
            self._inlet_temperature,
            self._device_status,
        )
        self._update_status()
        self._write_status_state()

    def _update_status(self) -> None:
        below_inlet = (
            self._setpoint is not None
            and self._inlet_temperature is not None
            and self._setpoint < self._inlet_temperature
        )
        service_required = self._device_status == DEVICE_STATUS_SERVICE_REQUIRED
        if not self._client.online:
            state = "disconnected"
        elif service_required:
            state = "service_required"
        elif below_inlet:
            state = "target_below_inlet"
        else:
            state = "ok"
        self._attr_native_value = state
        active_error = None if state == "ok" else state

        self._attr_available = connected_or_known_available(
            self._client.available,
            self._setpoint,
            self._inlet_temperature,
            self._device_status,
        )
        self._attr_extra_state_attributes = {
            "online": self._client.online,
            "connected": self._client.available,
            "active_error": active_error,
            "setpoint_temperature": self._setpoint,
            "inlet_temperature": self._inlet_temperature,
            "setpoint_below_inlet": below_inlet,
            "device_status": self._device_status,
            "device_service_required": service_required,
        }
        if below_inlet and self._setpoint is not None and self._inlet_temperature is not None:
            self._attr_extra_state_attributes["inlet_minus_setpoint"] = round(
                self._inlet_temperature - self._setpoint, 2
            )

    def _write_status_state(self, *, force: bool = False) -> None:
        """Write the entity only when stable error-status fields changed."""
        signature = self._status_write_signature()
        if not force and signature == self._last_written_status_signature:
            return
        self._last_written_status_signature = signature
        self._last_inlet_attribute_write_monotonic = time.monotonic()
        self.async_write_ha_state()

    def _should_refresh_inlet_attributes(self) -> bool:
        last_write = self._last_inlet_attribute_write_monotonic
        if last_write is None:
            return True
        return (
            time.monotonic() - last_write
        ) >= ERROR_STATUS_INLET_ATTRIBUTE_REFRESH_SECONDS

    def _status_write_signature(self) -> tuple[Any, ...]:
        """Return stable fields that should trigger a recorder-visible write."""
        attributes = self._attr_extra_state_attributes or {}
        return (
            self._attr_available,
            self._attr_native_value,
            attributes.get("online"),
            attributes.get("connected"),
            attributes.get("active_error"),
            attributes.get("setpoint_temperature"),
            attributes.get("setpoint_below_inlet"),
            attributes.get("device_status"),
            attributes.get("device_service_required"),
        )

    @staticmethod
    def _coerce_temperature(value: MeasurementValue) -> float | None:
        return coerce_float(value)


class StiebelDHEDiagnosticSensor(StiebelDHEEntityMixin, SensorEntity):
    """DHE client diagnostic sensor."""

    entity_description: StiebelDHEDiagnosticSensorEntityDescription
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(
        self,
        entry_id: str,
        name: str,
        client: DHEClient,
        description: StiebelDHEDiagnosticSensorEntityDescription,
    ) -> None:
        """Initialize the diagnostic sensor."""
        self.entity_description = description
        self._attr_translation_key = description.translation_key
        self._attr_icon = description.icon
        self._init_dhe_entity(
            entry_id=entry_id,
            key=description.key,
            name=name,
            client=client,
        )
        self._attr_entity_registry_enabled_default = (
            description.entity_registry_enabled_default
        )
        self._attr_should_poll = description.polls
        self._attr_available = False
        self._attr_native_value: int | float | str | None = None
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self._last_written_diagnostic_signature: tuple[Any, ...] | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to diagnostic updates."""
        self.async_on_remove(
            self._client.add_diagnostic_callback(self._handle_diagnostic_update)
        )
        self._apply_diagnostic_state(self._client.diagnostic_state)

    async def async_update(self) -> None:
        """Refresh dynamic diagnostic values."""
        self._apply_diagnostic_state(self._client.diagnostic_state)

    @callback
    def _handle_diagnostic_update(self, state: dict[str, Any]) -> None:
        """Handle diagnostic state updates from the persistent client."""
        self._apply_diagnostic_state(state)
        signature = self._diagnostic_write_signature()
        if signature == self._last_written_diagnostic_signature:
            return
        self._last_written_diagnostic_signature = signature
        self.async_write_ha_state()

    def _apply_diagnostic_state(self, state: dict[str, Any]) -> None:
        value = state.get(self.entity_description.diagnostic_key)
        if (
            value is None
            and self.entity_description.diagnostic_key == "last_reconnect_reason"
            and self._client.reconnect_count == 0
        ):
            value = self._no_reconnect_value()
        elif (
            value is None
            and self.entity_description.diagnostic_key == "next_reconnect_delay_seconds"
        ):
            value = 0
        self._attr_native_value = value if isinstance(value, (int, float, str)) else None
        self._attr_available = self._attr_native_value is not None
        self._attr_extra_state_attributes = {
            key: value
            for key, value in state.items()
            if (
                key != self.entity_description.diagnostic_key
                and key not in DIAGNOSTIC_VOLATILE_ATTRIBUTE_KEYS
            )
        }

    def _diagnostic_write_signature(self) -> tuple[Any, ...]:
        return (
            self._attr_available,
            self._attr_native_value,
            dict(self._attr_extra_state_attributes or {}),
        )

    def _no_reconnect_value(self) -> str:
        language = str(getattr(self.hass.config, "language", "") or "").lower()
        if language.startswith("de"):
            return "Kein Reconnect"
        return "No reconnect"
