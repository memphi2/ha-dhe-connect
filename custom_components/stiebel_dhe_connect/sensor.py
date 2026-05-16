"""Sensor platform for Stiebel DHE Connect."""

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
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfMass,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import (
    BRUSH_TIMER_PATH,
    DHEClient,
    ID_BATH_FILL_CURRENT_VOLUME,
    ID_BATH_FILL_REMAINING_VOLUME,
    ID_BRUSH_TIMER_REMAINING,
    ID_DEVICE_INFO,
    ID_DEVICE_STATUS,
    ID_ENERGY_CONSUMPTION_WEEK,
    ID_ENERGY_CONSUMPTION_YEAR,
    ID_ENERGY_CONSUMPTION_YEARS,
    ID_HEATING_ENERGY_TOTAL,
    ID_HOT_WATER_VOLUME_TOTAL,
    ID_INLET_TEMPERATURE,
    ID_LAST_USAGE_COST,
    ID_LAST_USAGE_ENERGY,
    ID_LAST_USAGE_TIME,
    ID_LAST_USAGE_WATER,
    ID_NOMINAL_POWER,
    ID_OPERATING_DURATION,
    ID_OUTLET_TEMPERATURE,
    ID_POSSIBLE_ENERGY_SAVING,
    ID_POSSIBLE_WATER_SAVING,
    ID_POWER_PERCENT,
    ID_PROTOCOL_VERSION,
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
    ID_SCALD_PROTECTION_TEMPERATURE_LIMIT,
    ID_SHOWER_TIMER_REMAINING,
    ID_WATER_CONSUMPTION_WEEK,
    ID_WATER_CONSUMPTION_YEAR,
    ID_WATER_CONSUMPTION_YEARS,
    ID_WATER_FLOW,
    MeasurementValue,
    SHOWER_TIMER_PATH,
)
from .client_mapping import DEVICE_STATUS_OPTIONS, DEVICE_STATUS_SERVICE_REQUIRED
from .entity_helpers import StiebelDHEEntityMixin
from .entity_state_helpers import (
    coerce_float,
    connected_or_known_available,
    format_minutes_duration,
    measurement_attribute_text,
    merge_state_attributes,
    value_available,
)
from .runtime_helpers import get_runtime_data


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


DEFAULT_ENABLED_SENSOR_KEYS = {
    "water_consumption_total",
    "energy_consumption_total",
}

# Reduce write frequency for high-churn live telemetry values. The tuple is
# (minimum absolute numeric delta, maximum seconds between writes).
SENSOR_WRITE_FILTERS: dict[str, tuple[float, float]] = {
    "inlet_temperature": (0.5, 120.0),
    "outlet_temperature": (0.5, 120.0),
    "water_flow": (1.0, 45.0),
    "power": (1.5, 45.0),
    "water_consumption_week": (1.0, 60.0),
    "water_consumption_year": (0.001, 60.0),
    "water_consumption_total": (0.001, 60.0),
    "energy_consumption_week": (0.05, 60.0),
    "energy_consumption_year": (0.05, 60.0),
    "energy_consumption_total": (0.05, 60.0),
    "saving_monitor_activation_rate": (1.0, 120.0),
    "saving_monitor_consumption_water": (0.25, 60.0),
    "saving_monitor_consumption_energy": (0.05, 60.0),
    "saving_monitor_consumption_co2": (0.05, 60.0),
    "saving_monitor_possible_water": (0.25, 60.0),
    "saving_monitor_possible_energy": (0.05, 60.0),
    "saving_monitor_possible_co2": (0.05, 60.0),
    "saving_monitor_possible_cost": (0.05, 60.0),
    "saving_monitor_real_water": (0.25, 60.0),
    "saving_monitor_real_energy": (0.05, 60.0),
    "saving_monitor_real_co2": (0.05, 60.0),
    "saving_monitor_real_cost": (0.05, 60.0),
}

CONNECTION_STATE_OPTIONS = (
    "starting",
    "connected",
    "reconnecting",
    "pairing_failed_waiting_manual_retry",
    "stopping",
    "stopped",
)

ERROR_STATUS_OPTIONS = (
    "ok",
    "disconnected",
    "service_required",
    "target_below_inlet",
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
        odb_id=ID_POWER_PERCENT,
    ),
    StiebelDHESensorEntityDescription(
        key="nominal_power",
        translation_key="nominal_power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        odb_id=ID_NOMINAL_POWER,
    ),
    StiebelDHESensorEntityDescription(
        key="operating_duration",
        translation_key="operating_duration",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:clock-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        odb_id=ID_OPERATING_DURATION,
    ),
    StiebelDHESensorEntityDescription(
        key="inlet_temperature",
        translation_key="inlet_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        odb_id=ID_INLET_TEMPERATURE,
    ),
    StiebelDHESensorEntityDescription(
        key="outlet_temperature",
        translation_key="outlet_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        odb_id=ID_OUTLET_TEMPERATURE,
    ),
    StiebelDHESensorEntityDescription(
        key="scald_protection_temperature_limit",
        translation_key="scald_protection_temperature_limit",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        icon="mdi:shield-thermometer",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        odb_id=ID_SCALD_PROTECTION_TEMPERATURE_LIMIT,
    ),
    StiebelDHESensorEntityDescription(
        key="device_status",
        translation_key="device_status",
        icon="mdi:wrench",
        device_class=SensorDeviceClass.ENUM,
        options=DEVICE_STATUS_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        odb_id=ID_DEVICE_STATUS,
    ),
    StiebelDHESensorEntityDescription(
        key="protocol_version",
        translation_key="protocol_version",
        icon="mdi:counter",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        odb_id=ID_PROTOCOL_VERSION,
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
        key="water_consumption_total",
        translation_key="water_consumption_total",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:water",
        odb_id=ID_WATER_CONSUMPTION_YEARS,
        source_command="set:ste.app.consumption:waterYears",
        period="years",
    ),
    StiebelDHESensorEntityDescription(
        key="hot_water_volume_total",
        translation_key="hot_water_volume_total",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:water",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        odb_id=ID_HOT_WATER_VOLUME_TOTAL,
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
        key="heating_energy_total",
        translation_key="heating_energy_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:lightning-bolt",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        odb_id=ID_HEATING_ENERGY_TOTAL,
    ),
    StiebelDHESensorEntityDescription(
        key="possible_energy_saving",
        translation_key="possible_energy_saving",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:lightning-bolt-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        odb_id=ID_POSSIBLE_ENERGY_SAVING,
    ),
    StiebelDHESensorEntityDescription(
        key="possible_water_saving",
        translation_key="possible_water_saving",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:water-percent",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        odb_id=ID_POSSIBLE_WATER_SAVING,
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
        key="energy_consumption_total",
        translation_key="energy_consumption_total",
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
        entity_registry_enabled_default=False,
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
        key="saving_monitor_consumption_water",
        translation_key="saving_monitor_consumption_water",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:water-percent",
        odb_id=ID_SAVING_MONITOR_WATER,
        source_command="set:ste.app.savingMonitor:consumption",
    ),
    StiebelDHESensorEntityDescription(
        key="saving_monitor_consumption_energy",
        translation_key="saving_monitor_consumption_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:lightning-bolt-circle",
        odb_id=ID_SAVING_MONITOR_ENERGY,
        source_command="set:ste.app.savingMonitor:consumption",
    ),
    StiebelDHESensorEntityDescription(
        key="saving_monitor_consumption_co2",
        translation_key="saving_monitor_consumption_co2",
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
        key="saving_monitor_possible_cost",
        translation_key="saving_monitor_possible_cost",
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
        key="saving_monitor_real_cost",
        translation_key="saving_monitor_real_cost",
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
        key="bath_fill_current_volume",
        translation_key="bath_fill_current_volume",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:bathtub",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        odb_id=ID_BATH_FILL_CURRENT_VOLUME,
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
    runtime = get_runtime_data(hass, entry)
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


class StiebelDHESensor(StiebelDHEEntityMixin, SensorEntity):
    """Converted DHE value sensor."""

    entity_description: StiebelDHESensorEntityDescription
    _attr_has_entity_name = True
    _attr_should_poll = False
    _unrecorded_attributes = frozenset({
        "chart",
        "activation_rate",
        "possible",
        "real",
        "consumption",
    })

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
        self._init_dhe_entity(
            entry_id=entry_id,
            key=description.key,
            name=name,
            client=client,
        )
        if description.key not in DEFAULT_ENABLED_SENSOR_KEYS:
            self._attr_entity_registry_enabled_default = False
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
        self._attr_available = False
        self._attr_native_value: float | str | None = None
        filter_values = SENSOR_WRITE_FILTERS.get(description.key)
        if filter_values is None:
            self._min_write_delta = None
            self._max_write_interval_seconds = None
        else:
            self._min_write_delta, self._max_write_interval_seconds = filter_values
        self._last_written_native_value: MeasurementValue = None
        self._last_written_monotonic: float | None = None

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
            self._last_written_native_value = self._attr_native_value
            self._last_written_monotonic = time.monotonic()

    def _convert_value(self, value: MeasurementValue) -> MeasurementValue:
        """Convert the raw client value for display."""
        if self.entity_description.attribute_key is not None:
            attributes = self._client.last_measurement_attributes.get(
                self.entity_description.odb_id,
                {},
            )
            return measurement_attribute_text(
                attributes,
                self.entity_description.attribute_key,
            )

        if not self.entity_description.timer_path and self.entity_description.key != "last_usage_time":
            return value

        return format_minutes_duration(value)

    def _update_extra_state_attributes(self) -> None:
        """Update static and dynamic sensor attributes."""
        self._attr_extra_state_attributes = merge_state_attributes(
            self._base_extra_state_attributes,
            self._client.last_measurement_attributes.get(
                self.entity_description.odb_id,
                {},
            ),
        )

    @callback
    def _handle_measurement_update(self, odb_id: int, value: MeasurementValue) -> None:
        """Handle converted measurement updates from the persistent client."""
        if odb_id != self.entity_description.odb_id:
            return

        self._update_extra_state_attributes()
        self._attr_native_value = self._convert_value(value)
        self._attr_available = self._attr_native_value is not None
        if not self._should_write_measurement_state(self._attr_native_value):
            return
        self._last_written_native_value = self._attr_native_value
        self._last_written_monotonic = time.monotonic()
        self.async_write_ha_state()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = value_available(available, self._attr_native_value)
        self.async_write_ha_state()

    def _should_write_measurement_state(self, new_value: MeasurementValue) -> bool:
        """Return whether this measurement update should write a new HA state."""
        previous_value = self._last_written_native_value
        if previous_value is None or new_value is None:
            return previous_value != new_value
        if previous_value == new_value:
            return False
        min_write_delta = self._min_write_delta
        max_write_interval_seconds = self._max_write_interval_seconds
        if min_write_delta is None or max_write_interval_seconds is None:
            return True

        previous_number = coerce_float(previous_value)
        new_number = coerce_float(new_value)
        if previous_number is None or new_number is None:
            return True
        if abs(new_number - previous_number) >= min_write_delta:
            return True

        last_written = self._last_written_monotonic
        if last_written is None:
            return True
        return (time.monotonic() - last_written) >= max_write_interval_seconds


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
        self.async_write_ha_state()

    @callback
    def _handle_setpoint_update(self, value: float) -> None:
        self._setpoint = self._coerce_temperature(value)
        self._update_status()
        self.async_write_ha_state()

    @callback
    def _handle_measurement_update(self, odb_id: int, value: MeasurementValue) -> None:
        if odb_id == ID_INLET_TEMPERATURE:
            self._inlet_temperature = self._coerce_temperature(value)
        elif odb_id == ID_DEVICE_STATUS:
            self._device_status = str(value) if isinstance(value, str) else None
        else:
            return
        self._update_status()
        self.async_write_ha_state()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        self._attr_available = connected_or_known_available(
            available,
            self._setpoint,
            self._inlet_temperature,
            self._device_status,
        )
        self._update_status()
        self.async_write_ha_state()

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
