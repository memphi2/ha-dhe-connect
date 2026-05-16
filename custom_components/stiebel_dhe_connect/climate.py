"""Climate platform for Stiebel DHE Connect."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import ClimateEntityFeature, HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import (
    ID_CHILD_SAFETY_ACTIVE,
    ID_CHILD_SAFETY_TEMPERATURE_LIMIT,
    ID_INLET_TEMPERATURE,
    ID_OUTLET_TEMPERATURE,
    ID_WATER_HEATING_ENABLED,
    DHEClient,
    DHEError,
    MeasurementValue,
)
from .config_entry_helpers import merged_entry_data
from .entity_helpers import StiebelDHEEntityMixin
from .entity_state_helpers import (
    CONF_INTERNAL_SCALD_PROTECTION,
    bounded_child_safety_temperature_limit,
    clamp_temperature,
    climate_max_temperature,
    normalize_internal_scald_protection,
)
from .runtime_helpers import get_runtime_data

_LOGGER = logging.getLogger(__name__)
_CLIMATE_FEATURE_TURN_ON = getattr(ClimateEntityFeature, "TURN_ON", 0)
_CLIMATE_FEATURE_TURN_OFF = getattr(ClimateEntityFeature, "TURN_OFF", 0)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the climate entity from a config entry."""
    runtime = get_runtime_data(hass, entry)
    async_add_entities([
        StiebelDHEClimate(
            entry=entry,
            entry_id=entry.entry_id,
            name=runtime.name,
            client=runtime.client,
        )
    ])


class StiebelDHEClimate(StiebelDHEEntityMixin, ClimateEntity):
    """Stiebel DHE setpoint entity with persistent local WebSocket session."""

    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | _CLIMATE_FEATURE_TURN_ON
        | _CLIMATE_FEATURE_TURN_OFF
    )
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_hvac_mode = HVACMode.HEAT
    _attr_min_temp = 20.0
    _attr_max_temp = 60.0
    _attr_target_temperature_step = 0.5
    _attr_should_poll = False
    _attr_translation_key = "water_heating"

    def __init__(
        self,
        entry: ConfigEntry,
        entry_id: str,
        name: str,
        client: DHEClient,
    ) -> None:
        """Initialize the entity."""
        self._internal_scald_protection = normalize_internal_scald_protection(
            merged_entry_data(entry).get(CONF_INTERNAL_SCALD_PROTECTION)
        )
        self._init_dhe_entity(
            entry_id=entry_id,
            key="setpoint",
            name=name,
            client=client,
        )
        self._attr_target_temperature: float | None = None
        self._attr_current_temperature: float | None = None
        self._attr_available = False
        self._connection_state = "starting"
        self._inlet_temperature: float | None = None
        self._outlet_temperature: float | None = None
        self._water_heating_enabled: bool | None = None
        self._child_safety_active: bool | None = None
        self._child_safety_temperature_limit: float | None = None
        self._child_safety_temperature_limit_raw: float | None = None
        self._target_before_heating_off: float | None = None
        self._update_extra_state_attributes()

    def _update_extra_state_attributes(self) -> None:
        """Update diagnostic attributes without doing I/O in properties."""
        target_below_inlet = self._target_below_inlet()
        internal_scald_protection = self._internal_scald_protection_option()
        self._attr_extra_state_attributes = {
            "communication_model": "persistent_socketio_websocket",
            "connection_state": self._connection_state,
            "readback_id": 0,
            "write_id": 66,
            "inlet_temperature": self._inlet_temperature,
            "outlet_temperature": self._outlet_temperature,
            "setpoint_below_inlet_temperature": target_below_inlet,
            "water_heating_enabled": self._water_heating_enabled,
            "child_safety_active": self._child_safety_active,
            "child_safety_temperature_limit": self._child_safety_temperature_limit,
            "internal_scald_protection": internal_scald_protection,
            "child_safety_temperature_limit_raw": (
                self._child_safety_temperature_limit_raw
            ),
        }
        if target_below_inlet:
            self._attr_extra_state_attributes["inlet_minus_setpoint"] = round(
                self._inlet_temperature - self._attr_target_temperature, 2
            )

    async def async_added_to_hass(self) -> None:
        """Start persistent DHE connection and subscribe to value updates."""
        self.async_on_remove(
            self._client.add_setpoint_callback(self._handle_setpoint_update)
        )
        self.async_on_remove(
            self._client.add_availability_callback(self._handle_availability_update)
        )
        self.async_on_remove(
            self._client.add_measurement_callback(self._handle_measurement_update)
        )
        self._sync_temperatures_from_measurements()
        self._sync_hvac_mode_from_measurements()
        self._sync_max_temperature_from_measurements()
        if self._client.last_setpoint is not None:
            self._attr_target_temperature = self._client.last_setpoint
            self._attr_available = self._client.available
            self._connection_state = (
                "connected" if self._client.available else "unavailable"
            )
            self._update_extra_state_attributes()

    @callback
    def _handle_setpoint_update(self, value: float) -> None:
        """Handle setpoint updates from the persistent client."""
        self._attr_target_temperature = value
        if self._attr_hvac_mode != HVACMode.OFF:
            self._target_before_heating_off = value
        self._attr_available = True
        self._connection_state = "connected"
        self._update_extra_state_attributes()
        self.async_write_ha_state()

    @callback
    def _handle_measurement_update(self, odb_id: int, value: MeasurementValue) -> None:
        """Handle measurement updates for inlet and outlet temperatures."""
        if odb_id == ID_INLET_TEMPERATURE:
            self._inlet_temperature = self._coerce_temperature(value)
        elif odb_id == ID_OUTLET_TEMPERATURE:
            self._outlet_temperature = self._coerce_temperature(value)
        elif odb_id == ID_WATER_HEATING_ENABLED:
            self._water_heating_enabled = bool(value)
            self._attr_hvac_mode = (
                HVACMode.HEAT if self._water_heating_enabled else HVACMode.OFF
            )
        elif odb_id == ID_CHILD_SAFETY_ACTIVE:
            self._child_safety_active = bool(value)
            self._apply_dynamic_max_temperature()
        elif odb_id == ID_CHILD_SAFETY_TEMPERATURE_LIMIT:
            self._apply_child_safety_temperature_limit(value)
            self._apply_dynamic_max_temperature()
        else:
            return

        self._update_extra_state_attributes()
        self.async_write_ha_state()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates.

        Strict live availability: expose this entity only while the DHE connection
        is active.
        """
        if available:
            self._attr_available = True
            self._connection_state = "connected"
        else:
            self._attr_available = False
            self._connection_state = "unavailable"

        self._update_extra_state_attributes()
        self.async_write_ha_state()

    def _sync_temperatures_from_measurements(self) -> None:
        """Initialize inlet/outlet values from the last known measurements."""
        self._inlet_temperature = self._coerce_temperature(
            self._client.last_measurements.get(ID_INLET_TEMPERATURE)
        )
        self._outlet_temperature = self._coerce_temperature(
            self._client.last_measurements.get(ID_OUTLET_TEMPERATURE)
        )

    def _sync_hvac_mode_from_measurements(self) -> None:
        """Initialize HVAC mode from ODB id 33."""
        value = self._client.last_measurements.get(ID_WATER_HEATING_ENABLED)
        if value is None:
            self._water_heating_enabled = None
            return
        self._water_heating_enabled = bool(value)
        self._attr_hvac_mode = (
            HVACMode.HEAT if self._water_heating_enabled else HVACMode.OFF
        )

    def _sync_max_temperature_from_measurements(self) -> None:
        """Initialize dynamic max temperature from ODB ids 4/5."""
        child_safety_active = self._client.last_measurements.get(ID_CHILD_SAFETY_ACTIVE)
        if child_safety_active is not None:
            self._child_safety_active = bool(child_safety_active)

        configured_maximum = self._client.last_measurements.get(
            ID_CHILD_SAFETY_TEMPERATURE_LIMIT
        )
        self._apply_child_safety_temperature_limit(configured_maximum)
        self._apply_dynamic_max_temperature()

    def _apply_dynamic_max_temperature(self) -> None:
        """Apply max temperature depending on configured limit override."""
        self._attr_max_temp = climate_max_temperature(
            internal_scald_protection=self._internal_scald_protection_option(),
            child_safety_active=self._child_safety_active,
            child_safety_temperature_limit=self._child_safety_temperature_limit,
            minimum=self._attr_min_temp,
            maximum=60.0,
        )

    def _apply_child_safety_temperature_limit(
        self,
        value: MeasurementValue,
    ) -> None:
        """Store raw and effective child-safety temperature limits."""
        self._child_safety_temperature_limit_raw = self._coerce_temperature(value)
        self._child_safety_temperature_limit = bounded_child_safety_temperature_limit(
            self._child_safety_temperature_limit_raw,
            internal_scald_protection=self._internal_scald_protection_option(),
            minimum=self._attr_min_temp,
            maximum=60.0,
        )

    def _internal_scald_protection_option(self) -> str:
        """Return the configured local jumper option."""
        return self._internal_scald_protection

    @staticmethod
    def _coerce_temperature(value: MeasurementValue) -> float | None:
        """Convert a measurement value to float temperature where possible."""
        if value is None or isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _target_below_inlet(self) -> bool:
        """Return True when the configured target is below current inlet temperature."""
        if self._attr_target_temperature is None or self._inlet_temperature is None:
            return False
        return self._attr_target_temperature < self._inlet_temperature

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature and update state from write readback."""
        if ATTR_TEMPERATURE not in kwargs:
            return

        temperature = clamp_temperature(
            kwargs[ATTR_TEMPERATURE],
            minimum=self._attr_min_temp,
            maximum=self._attr_max_temp,
        )
        if temperature is None:
            return

        try:
            if self._attr_hvac_mode == HVACMode.OFF or self._water_heating_enabled is False:
                self._water_heating_enabled = await self._client.set_water_heating_enabled(True)
                self._attr_hvac_mode = (
                    HVACMode.HEAT if self._water_heating_enabled else HVACMode.OFF
                )
                if not self._water_heating_enabled:
                    raise DHEError("Could not enable DHE heating before setting temperature")
            self._attr_target_temperature = await self._client.set_temperature(temperature)
            self._target_before_heating_off = self._attr_target_temperature
            self._attr_available = True
            self._connection_state = "connected"
            self._update_extra_state_attributes()
            self.async_write_ha_state()
        except DHEError as err:
            _LOGGER.error("Could not set DHE temperature: %s", err)
            raise

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode on the DHE climate entity."""
        if hvac_mode == HVACMode.OFF:
            if self._attr_target_temperature is not None:
                self._target_before_heating_off = self._attr_target_temperature
            try:
                self._water_heating_enabled = await self._client.set_water_heating_enabled(False)
            except DHEError as err:
                _LOGGER.error("Could not switch DHE heating off: %s", err)
                raise
            self._attr_hvac_mode = (
                HVACMode.HEAT if self._water_heating_enabled else HVACMode.OFF
            )
            self._attr_available = True
            self._connection_state = "connected"
            self._update_extra_state_attributes()
            self.async_write_ha_state()
            return

        if hvac_mode == HVACMode.HEAT:
            try:
                self._water_heating_enabled = await self._client.set_water_heating_enabled(True)
            except DHEError as err:
                _LOGGER.error("Could not switch DHE heating on: %s", err)
                raise
            self._attr_hvac_mode = (
                HVACMode.HEAT if self._water_heating_enabled else HVACMode.OFF
            )
            if self._water_heating_enabled:
                restore_target = self._target_before_heating_off
                if restore_target is None:
                    restore_target = self._attr_target_temperature or self._client.last_setpoint
                if restore_target is not None:
                    restore_target = clamp_temperature(
                        restore_target,
                        minimum=self._attr_min_temp,
                        maximum=self._attr_max_temp,
                    )
                if restore_target is not None:
                    try:
                        self._attr_target_temperature = await self._client.set_temperature(
                            float(restore_target)
                        )
                        self._target_before_heating_off = self._attr_target_temperature
                    except DHEError as err:
                        _LOGGER.warning(
                            "DHE heating enabled, but could not restore previous target temperature: %s",
                            err,
                        )
            else:
                _LOGGER.warning(
                    "DHE returned water_heating_enabled=False after heating ON command"
                )
            self._attr_available = True
            self._connection_state = "connected"
            self._update_extra_state_attributes()
            self.async_write_ha_state()
            return

        raise ValueError(f"Unsupported HVAC mode: {hvac_mode}")

    async def async_turn_on(self) -> None:
        """Turn water heating on."""
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        """Turn water heating off."""
        await self.async_set_hvac_mode(HVACMode.OFF)
