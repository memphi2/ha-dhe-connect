"""Sensor platform for Stiebel DHE Connect."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfMass,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import (
    BRUSH_TIMER_PATH,
    DHEClient,
    ID_BATH_FILL_REMAINING_VOLUME,
    ID_BRUSH_TIMER_REMAINING,
    ID_CONFIGURED_POWER,
    ID_DEVICE_INFO,
    ID_ENERGY_CONSUMPTION_WEEK,
    ID_ENERGY_CONSUMPTION_YEAR,
    ID_ENERGY_CONSUMPTION_YEARS,
    ID_INTERNAL_TEMPERATURE_1,
    ID_INTERNAL_TEMPERATURE_2,
    ID_LAST_USAGE_COST,
    ID_LAST_USAGE_ENERGY,
    ID_LAST_USAGE_TIME,
    ID_LAST_USAGE_WATER,
    ID_POWER,
    ID_SAVING_MONITOR_ACTIVATION_RATE,
    ID_SAVING_MONITOR_CO2,
    ID_SAVING_MONITOR_ENERGY,
    ID_SAVING_MONITOR_POSSIBLE_CO2,
    ID_SAVING_MONITOR_POSSIBLE_ENERGY,
    ID_SAVING_MONITOR_POSSIBLE_VALUE,
    ID_SAVING_MONITOR_POSSIBLE_WATER,
    ID_SAVING_MONITOR_REAL_CO2,
    ID_SAVING_MONITOR_REAL_ENERGY,
    ID_SAVING_MONITOR_REAL_VALUE,
    ID_SAVING_MONITOR_REAL_WATER,
    ID_SAVING_MONITOR_WATER,
    ID_SHOWER_TIMER_REMAINING,
    ID_WATER_CONSUMPTION_WEEK,
    ID_WATER_CONSUMPTION_YEAR,
    ID_WATER_CONSUMPTION_YEARS,
    ID_WATER_FLOW,
    MeasurementValue,
    SHOWER_TIMER_PATH,
)
from .const import DOMAIN


@dataclass(frozen=True, kw_only=True)
class StiebelDHESensorEntityDescription(SensorEntityDescription):
    """Describe a converted DHE sensor."""

    odb_id: int
    attribute_key: str | None = None
    timer_path: str | None = None
    timer_property: str | None = None
    source_command: str | None = None
    period: str | None = None


@dataclass(frozen=True, kw_only=True)
class StiebelDHEDiagnosticSensorEntityDescription(SensorEntityDescription):
    """Describe a DHE client diagnostic sensor."""

    diagnostic_key: str
    polls: bool = False


DEFAULT_DISABLED_SENSOR_KEYS = {
    "configured_power",
    "water_consumption_week",
    "water_consumption_year",
    "water_consumption_years",
    "energy_consumption_week",
    "energy_consumption_year",
    "energy_consumption_years",
    "saving_monitor_water",
    "saving_monitor_energy",
    "saving_monitor_co2",
    "saving_monitor_activation_rate",
    "saving_monitor_possible_water",
    "saving_monitor_possible_energy",
    "saving_monitor_possible_co2",
    "saving_monitor_possible_value",
    "saving_monitor_real_water",
    "saving_monitor_real_energy",
    "saving_monitor_real_co2",
    "saving_monitor_real_value",
}

CONNECTION_STATE_OPTIONS = (
    "starting",
    "connected",
    "reconnecting",
    "pairing_failed_waiting_manual_retry",
    "stopping",
    "stopped",
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
        entity_registry_enabled_default=False,
    ),
)


SENSOR_DESCRIPTIONS: tuple[StiebelDHESensorEntityDescription, ...] = (
    StiebelDHESensorEntityDescription(
        key="water_flow",
        translation_key="water_flow",
        native_unit_of_measurement=UnitOfVolumeFlowRate.LITERS_PER_MINUTE,
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        odb_id=ID_WATER_FLOW,
    ),
    StiebelDHESensorEntityDescription(
        key="power",
        translation_key="power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        odb_id=ID_POWER,
    ),
    StiebelDHESensorEntityDescription(
        key="configured_power",
        translation_key="configured_power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        odb_id=ID_CONFIGURED_POWER,
    ),
    StiebelDHESensorEntityDescription(
        key="internal_temperature_1",
        translation_key="internal_temperature_1",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        odb_id=ID_INTERNAL_TEMPERATURE_1,
    ),
    StiebelDHESensorEntityDescription(
        key="internal_temperature_2",
        translation_key="internal_temperature_2",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        odb_id=ID_INTERNAL_TEMPERATURE_2,
    ),
    StiebelDHESensorEntityDescription(
        key="water_consumption_week",
        translation_key="water_consumption_week",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:water",
        odb_id=ID_WATER_CONSUMPTION_WEEK,
        source_command="set:ste.app.consumption:waterWeek",
        period="week",
    ),
    StiebelDHESensorEntityDescription(
        key="water_consumption_year",
        translation_key="water_consumption_year",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:water",
        odb_id=ID_WATER_CONSUMPTION_YEAR,
        source_command="set:ste.app.consumption:waterYear",
        period="year",
    ),
    StiebelDHESensorEntityDescription(
        key="water_consumption_years",
        translation_key="water_consumption_years",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:water",
        odb_id=ID_WATER_CONSUMPTION_YEARS,
        source_command="set:ste.app.consumption:waterYears",
        period="years",
    ),
    StiebelDHESensorEntityDescription(
        key="energy_consumption_week",
        translation_key="energy_consumption_week",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        odb_id=ID_ENERGY_CONSUMPTION_WEEK,
        source_command="set:ste.app.consumption:energyWeek",
        period="week",
    ),
    StiebelDHESensorEntityDescription(
        key="energy_consumption_year",
        translation_key="energy_consumption_year",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        odb_id=ID_ENERGY_CONSUMPTION_YEAR,
        source_command="set:ste.app.consumption:energyYear",
        period="year",
    ),
    StiebelDHESensorEntityDescription(
        key="energy_consumption_years",
        translation_key="energy_consumption_years",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        odb_id=ID_ENERGY_CONSUMPTION_YEARS,
        source_command="set:ste.app.consumption:energyYears",
        period="years",
    ),
    StiebelDHESensorEntityDescription(
        key="last_usage_water",
        translation_key="last_usage_water",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:water-check",
        odb_id=ID_LAST_USAGE_WATER,
        source_command="set:ste.app.consumption:lastUsage",
    ),
    StiebelDHESensorEntityDescription(
        key="last_usage_energy",
        translation_key="last_usage_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:lightning-bolt",
        odb_id=ID_LAST_USAGE_ENERGY,
        source_command="set:ste.app.consumption:lastUsage",
    ),
    StiebelDHESensorEntityDescription(
        key="last_usage_time",
        translation_key="last_usage_time",
        icon="mdi:timer-outline",
        odb_id=ID_LAST_USAGE_TIME,
        source_command="set:ste.app.consumption:lastUsage",
    ),
    StiebelDHESensorEntityDescription(
        key="last_usage_cost",
        translation_key="last_usage_cost",
        native_unit_of_measurement="EUR",
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:cash",
        odb_id=ID_LAST_USAGE_COST,
        source_command="set:ste.app.consumption:lastUsage",
    ),
    StiebelDHESensorEntityDescription(
        key="saving_monitor_water",
        translation_key="saving_monitor_water",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:water-percent",
        odb_id=ID_SAVING_MONITOR_WATER,
        source_command="set:ste.app.savingMonitor:consumption",
    ),
    StiebelDHESensorEntityDescription(
        key="saving_monitor_energy",
        translation_key="saving_monitor_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:lightning-bolt-circle",
        odb_id=ID_SAVING_MONITOR_ENERGY,
        source_command="set:ste.app.savingMonitor:consumption",
    ),
    StiebelDHESensorEntityDescription(
        key="saving_monitor_co2",
        translation_key="saving_monitor_co2",
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:molecule-co2",
        odb_id=ID_SAVING_MONITOR_CO2,
        source_command="set:ste.app.savingMonitor:consumption",
    ),
    StiebelDHESensorEntityDescription(
        key="saving_monitor_activation_rate",
        translation_key="saving_monitor_activation_rate",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        icon="mdi:leaf-circle",
        odb_id=ID_SAVING_MONITOR_ACTIVATION_RATE,
        source_command="set:ste.app.savingMonitor:ActivationRate",
    ),
    StiebelDHESensorEntityDescription(
        key="saving_monitor_possible_water",
        translation_key="saving_monitor_possible_water",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:water-plus",
        odb_id=ID_SAVING_MONITOR_POSSIBLE_WATER,
        source_command="set:ste.app.savingMonitor:possible",
    ),
    StiebelDHESensorEntityDescription(
        key="saving_monitor_possible_energy",
        translation_key="saving_monitor_possible_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:lightning-bolt-outline",
        odb_id=ID_SAVING_MONITOR_POSSIBLE_ENERGY,
        source_command="set:ste.app.savingMonitor:possible",
    ),
    StiebelDHESensorEntityDescription(
        key="saving_monitor_possible_co2",
        translation_key="saving_monitor_possible_co2",
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:molecule-co2",
        odb_id=ID_SAVING_MONITOR_POSSIBLE_CO2,
        source_command="set:ste.app.savingMonitor:possible",
    ),
    StiebelDHESensorEntityDescription(
        key="saving_monitor_possible_value",
        translation_key="saving_monitor_possible_value",
        native_unit_of_measurement="EUR",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        icon="mdi:cash-plus",
        odb_id=ID_SAVING_MONITOR_POSSIBLE_VALUE,
        source_command="set:ste.app.savingMonitor:possible",
    ),
    StiebelDHESensorEntityDescription(
        key="saving_monitor_real_water",
        translation_key="saving_monitor_real_water",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:water-check",
        odb_id=ID_SAVING_MONITOR_REAL_WATER,
        source_command="set:ste.app.savingMonitor:real",
    ),
    StiebelDHESensorEntityDescription(
        key="saving_monitor_real_energy",
        translation_key="saving_monitor_real_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:lightning-bolt-circle",
        odb_id=ID_SAVING_MONITOR_REAL_ENERGY,
        source_command="set:ste.app.savingMonitor:real",
    ),
    StiebelDHESensorEntityDescription(
        key="saving_monitor_real_co2",
        translation_key="saving_monitor_real_co2",
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:molecule-co2",
        odb_id=ID_SAVING_MONITOR_REAL_CO2,
        source_command="set:ste.app.savingMonitor:real",
    ),
    StiebelDHESensorEntityDescription(
        key="saving_monitor_real_value",
        translation_key="saving_monitor_real_value",
        native_unit_of_measurement="EUR",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        icon="mdi:cash-check",
        odb_id=ID_SAVING_MONITOR_REAL_VALUE,
        source_command="set:ste.app.savingMonitor:real",
    ),
    StiebelDHESensorEntityDescription(
        key="bath_fill_remaining_volume",
        translation_key="bath_fill_remaining_volume",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:bathtub",
        odb_id=ID_BATH_FILL_REMAINING_VOLUME,
        source_command="derived:bath_fill_remaining",
    ),
    StiebelDHESensorEntityDescription(
        key="brush_timer_remaining",
        translation_key="brush_timer_remaining",
        icon="mdi:toothbrush",
        odb_id=ID_BRUSH_TIMER_REMAINING,
        timer_path=BRUSH_TIMER_PATH,
        timer_property="remainingMilliseconds",
    ),
    StiebelDHESensorEntityDescription(
        key="shower_timer_remaining",
        translation_key="shower_timer_remaining",
        icon="mdi:timer-sand",
        odb_id=ID_SHOWER_TIMER_REMAINING,
        timer_path=SHOWER_TIMER_PATH,
        timer_property="remainingMilliseconds",
    ),
    StiebelDHESensorEntityDescription(
        key="device_info",
        translation_key="device_info",
        icon="mdi:information-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        odb_id=ID_DEVICE_INFO,
        source_command="set:ste.common.version:*",
    ),
    StiebelDHESensorEntityDescription(
        key="product_id",
        translation_key="product_id",
        icon="mdi:identifier",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        odb_id=ID_DEVICE_INFO,
        attribute_key="device_id",
        source_command="set:ste.common.version:gadgetData",
    ),
    StiebelDHESensorEntityDescription(
        key="wlan_mac",
        translation_key="wlan_mac",
        icon="mdi:wifi",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        odb_id=ID_DEVICE_INFO,
        attribute_key="wlan_mac",
        source_command="set:ste.common.version:gadgetData",
    ),
    StiebelDHESensorEntityDescription(
        key="bluetooth_mac",
        translation_key="bluetooth_mac",
        icon="mdi:bluetooth",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        odb_id=ID_DEVICE_INFO,
        attribute_key="bluetooth_mac",
        source_command="set:ste.common.version:gadgetData",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DHE sensors from a config entry."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            StiebelDHESensor(
                entry_id=entry.entry_id,
                name=runtime.name,
                client=runtime.client,
                description=description,
            )
            for description in SENSOR_DESCRIPTIONS
        ]
        + [
            StiebelDHEReconnectCountSensor(
                entry_id=entry.entry_id,
                name=runtime.name,
                client=runtime.client,
            )
        ]
        + [
            StiebelDHEErrorStatusSensor(
                entry_id=entry.entry_id,
                name=runtime.name,
                client=runtime.client,
            )
        ]
        + [
            StiebelDHEDiagnosticSensor(
                entry_id=entry.entry_id,
                name=runtime.name,
                client=runtime.client,
                description=description,
            )
            for description in DIAGNOSTIC_SENSOR_DESCRIPTIONS
        ]
    )


class StiebelDHESensor(SensorEntity):
    """Converted DHE value sensor."""

    entity_description: StiebelDHESensorEntityDescription
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry_id: str,
        name: str,
        client: DHEClient,
        description: StiebelDHESensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        self._attr_translation_key = description.translation_key
        self._attr_unique_id = f"stiebel_dhe_connect_{entry_id}_{description.key}"
        if description.key in DEFAULT_DISABLED_SENSOR_KEYS:
            self._attr_entity_registry_enabled_default = False
        self._attr_device_info = {
            "identifiers": {(DOMAIN, client.host)},
            "manufacturer": "STIEBEL ELTRON",
            "model": "DHE Connect",
            "name": name,
        }
        if description.timer_path:
            self._base_extra_state_attributes = {
                "timer_path": description.timer_path,
                "timer_property": description.timer_property,
            }
        elif description.source_command:
            self._base_extra_state_attributes = {
                "source_command": description.source_command,
            }
            if description.period is not None:
                self._base_extra_state_attributes["period"] = description.period
        else:
            self._base_extra_state_attributes = {"odb_id": description.odb_id}
        self._attr_extra_state_attributes = dict(self._base_extra_state_attributes)
        self._client = client
        self._attr_available = False
        self._attr_native_value: float | str | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to DHE measurements and start the persistent session."""
        self.async_on_remove(
            self._client.add_measurement_callback(self._handle_measurement_update)
        )
        self.async_on_remove(
            self._client.add_availability_callback(self._handle_availability_update)
        )

        last_value = self._client.last_measurements.get(self.entity_description.odb_id)
        if last_value is not None:
            self._update_extra_state_attributes()
            self._attr_native_value = self._convert_value(last_value)
            self._attr_available = self._attr_native_value is not None

    def _convert_value(self, value: MeasurementValue) -> MeasurementValue:
        """Convert the raw client value for display."""
        if self.entity_description.attribute_key is not None:
            attribute_value = self._client.last_measurement_attributes.get(
                self.entity_description.odb_id,
                {},
            ).get(self.entity_description.attribute_key)
            if attribute_value in (None, ""):
                return None
            return str(attribute_value)

        if not self.entity_description.timer_path and self.entity_description.key != "last_usage_time":
            return value

        total_seconds = max(0, int(round(float(value) * 60)))
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}:{seconds:02d}"

    def _update_extra_state_attributes(self) -> None:
        """Update static and dynamic sensor attributes."""
        attributes = dict(self._base_extra_state_attributes)
        attributes.update(self._client.last_measurement_attributes.get(self.entity_description.odb_id, {}))
        self._attr_extra_state_attributes = attributes

    @callback
    def _handle_measurement_update(self, odb_id: int, value: MeasurementValue) -> None:
        """Handle converted measurement updates from the persistent client."""
        if odb_id != self.entity_description.odb_id:
            return

        self._update_extra_state_attributes()
        self._attr_native_value = self._convert_value(value)
        self._attr_available = self._attr_native_value is not None
        self.async_write_ha_state()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = available and self._attr_native_value is not None
        self.async_write_ha_state()


class StiebelDHEReconnectCountSensor(SensorEntity):
    """DHE reconnect count diagnostic sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:restart"
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_translation_key = "reconnect_count"

    def __init__(self, entry_id: str, name: str, client: DHEClient) -> None:
        """Initialize the reconnect count sensor."""
        self._attr_unique_id = f"stiebel_dhe_connect_{entry_id}_reconnect_count"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, client.host)},
            "manufacturer": "STIEBEL ELTRON",
            "model": "DHE Connect",
            "name": name,
        }
        self._client = client
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


class StiebelDHEErrorStatusSensor(SensorEntity):
    """Human-readable general error status."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "temperature_error_status"
    _attr_icon = "mdi:alert-octagon-outline"

    def __init__(self, entry_id: str, name: str, client: DHEClient) -> None:
        """Initialize the general error status sensor."""
        self._attr_unique_id = f"stiebel_dhe_connect_{entry_id}_temperature_error_status"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, client.host)},
            "manufacturer": "STIEBEL ELTRON",
            "model": "DHE Connect",
            "name": name,
        }
        self._client = client
        self._setpoint: float | None = None
        self._inlet_temperature: float | None = None
        self._attr_available = False
        self._attr_native_value: str | None = None
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
            self._client.last_measurements.get(ID_INTERNAL_TEMPERATURE_1)
        )
        self._update_status()
        self.async_write_ha_state()

    @callback
    def _handle_setpoint_update(self, value: float) -> None:
        self._setpoint = self._coerce_temperature(value)
        self._update_status()
        self.async_write_ha_state()

    @callback
    def _handle_measurement_update(self, odb_id: int, value: MeasurementValue) -> None:
        if odb_id != ID_INTERNAL_TEMPERATURE_1:
            return
        self._inlet_temperature = self._coerce_temperature(value)
        self._update_status()
        self.async_write_ha_state()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        self._attr_available = (
            available
            or self._setpoint is not None
            or self._inlet_temperature is not None
        )
        self._update_status()
        self.async_write_ha_state()

    def _update_status(self) -> None:
        below_inlet = (
            self._setpoint is not None
            and self._inlet_temperature is not None
            and self._setpoint < self._inlet_temperature
        )
        language = str(getattr(self.hass.config, "language", "") or "").lower() if self.hass else ""
        if not self._client.online:
            self._attr_native_value = "Nicht verbunden" if language.startswith("de") else "Disconnected"
            active_error = "disconnected"
        elif below_inlet:
            self._attr_native_value = (
                "Solltemperatur unter Zulauftemperatur"
                if language.startswith("de")
                else "Target temperature below inlet temperature"
            )
            active_error = "target_below_inlet"
        else:
            self._attr_native_value = "OK"
            active_error = None

        self._attr_available = (
            self._client.available
            or self._setpoint is not None
            or self._inlet_temperature is not None
        )
        self._attr_extra_state_attributes = {
            "online": self._client.online,
            "connected": self._client.available,
            "active_error": active_error,
            "setpoint_temperature": self._setpoint,
            "inlet_temperature": self._inlet_temperature,
            "setpoint_below_inlet": below_inlet,
        }
        if below_inlet and self._setpoint is not None and self._inlet_temperature is not None:
            self._attr_extra_state_attributes["inlet_minus_setpoint"] = round(
                self._inlet_temperature - self._setpoint, 2
            )

    @staticmethod
    def _coerce_temperature(value: MeasurementValue) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


class StiebelDHEDiagnosticSensor(SensorEntity):
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
        self._attr_unique_id = f"stiebel_dhe_connect_{entry_id}_{description.key}"
        self._attr_should_poll = description.polls
        self._attr_device_info = {
            "identifiers": {(DOMAIN, client.host)},
            "manufacturer": "STIEBEL ELTRON",
            "model": "DHE Connect",
            "name": name,
        }
        self._client = client
        self._attr_available = False
        self._attr_native_value: int | str | None = None
        self._attr_extra_state_attributes = {}

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
        self.async_write_ha_state()

    def _apply_diagnostic_state(self, state: dict[str, Any]) -> None:
        value = state.get(self.entity_description.diagnostic_key)
        if (
            value is None
            and self.entity_description.diagnostic_key == "last_reconnect_reason"
            and self._client.reconnect_count == 0
        ):
            value = self._no_reconnect_value()
        self._attr_native_value = value if isinstance(value, (int, str)) else None
        self._attr_available = self._attr_native_value is not None
        self._attr_extra_state_attributes = {
            key: value
            for key, value in state.items()
            if key != self.entity_description.diagnostic_key
        }

    def _no_reconnect_value(self) -> str:
        language = str(getattr(self.hass.config, "language", "") or "").lower()
        if language.startswith("de"):
            return "Kein Reconnect"
        return "No reconnect"
