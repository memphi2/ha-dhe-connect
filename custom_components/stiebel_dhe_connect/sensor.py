"""Sensor platform for DHE Connect."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass
import time
from typing import Any, cast

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

from .client import DHEClient
from .client_types import DHEError, MeasurementValue
from .client_web_version import WEB_INTERFACE_VERSION_SOURCE
from .async_helpers import create_background_task
from .client_mapping import (
    DEVICE_STATUS_OPTIONS,
    DEVICE_STATUS_SERVICE_REQUIRED as _DEVICE_STATUS_SERVICE_REQUIRED,
)
from .entity_helpers import StiebelDHEEntityMixin
from .entity_state_helpers import (
    coerce_float,
    format_minutes_duration,
    measurement_attribute_text,
    merge_state_attributes,
    switch_state_from_value,
    value_available,
)
from .protocol import (
    BRUSH_TIMER_DEFAULT_DURATION_MINUTES,
    BRUSH_TIMER_PATH,
    ID_BATH_FILL_CURRENT_VOLUME,
    ID_BATH_FILL_REMAINING_VOLUME,
    ID_BRUSH_TIMER_ACTIVATION,
    ID_BRUSH_TIMER_DURATION,
    ID_BRUSH_TIMER_REMAINING,
    ID_DEVICE_INFO,
    ID_DEVICE_STATUS,
    ID_ENERGY_CONSUMPTION_WEEK,
    ID_ENERGY_CONSUMPTION_YEAR,
    ID_ENERGY_CONSUMPTION_YEARS,
    ID_ODB_HEATING_ENERGY,
    ID_ODB_HOT_WATER_VOLUME,
    ID_INLET_TEMPERATURE,
    ID_LAST_USAGE_COST,
    ID_LAST_USAGE_ENERGY,
    ID_LAST_USAGE_TIME,
    ID_LAST_USAGE_WATER,
    ID_NOMINAL_POWER,
    ID_OPERATING_DURATION,
    ID_OUTLET_TEMPERATURE,
    ID_ODB_POSSIBLE_ENERGY_SAVING,
    ID_ODB_ACTUAL_WATER_SAVING,
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
    ID_SHOWER_TIMER_ACTIVATION,
    ID_SHOWER_TIMER_DURATION,
    ID_SHOWER_TIMER_REMAINING,
    ID_WELLNESS_TIME_NORMALIZED,
    ID_WATER_CONSUMPTION_WEEK,
    ID_WATER_CONSUMPTION_YEAR,
    ID_WATER_CONSUMPTION_YEARS,
    ID_WATER_FLOW,
    ODB_ZERO_REQUEST_READBACK_IGNORE_IDS,
    SHOWER_TIMER_DEFAULT_DURATION_MINUTES,
    SHOWER_TIMER_PATH,
)
from .runtime_helpers import get_runtime_data
from .sensor_diagnostics import (
    DIAGNOSTIC_SENSOR_DESCRIPTIONS,
    StiebelDHEDiagnosticSensor,
    StiebelDHEErrorStatusSensor,
    StiebelDHEReconnectCountSensor,
)

PARALLEL_UPDATES = 0
DEVICE_STATUS_SERVICE_REQUIRED = _DEVICE_STATUS_SERVICE_REQUIRED
TIMER_COUNTDOWN_INTERVAL_SECONDS = 1.0


@dataclass(frozen=True, kw_only=True)
class StiebelDHESensorEntityDescription(SensorEntityDescription):
    """Describe a converted DHE sensor."""

    odb_id: int
    attribute_key: str | None = None
    timer_activation_odb_id: int | None = None
    timer_duration_odb_id: int | None = None
    timer_default_duration_minutes: float | None = None
    timer_path: str | None = None
    timer_property: str | None = None
    source_command: str | None = None
    period: str | None = None
    available_without_value: bool = False


DEFAULT_ENABLED_SENSOR_KEYS = {
    "power",
    "water_flow",
    "water_consumption_total",
    "energy_consumption_total",
}

# Reduce write frequency for high-churn telemetry values. The tuple is
# (minimum absolute numeric delta, maximum seconds between writes). Live
# flow/power values intentionally keep a small threshold; timer remaining values
# and bath-fill volumes are not listed here because every runtime change should
# be visible in Home Assistant.
SENSOR_WRITE_FILTERS: dict[str, tuple[float, float]] = {
    "inlet_temperature": (0.5, 120.0),
    "outlet_temperature": (0.5, 120.0),
    "water_flow": (0.2, 45.0),
    "power": (0.2, 45.0),
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
SENSOR_DESCRIPTIONS: tuple[StiebelDHESensorEntityDescription, ...] = (
    StiebelDHESensorEntityDescription(
        key="water_flow",
        translation_key="water_flow",
        native_unit_of_measurement=UnitOfVolumeFlowRate.LITERS_PER_MINUTE,
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
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
        icon="mdi:thermometer-alert",
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
        source_command=WEB_INTERFACE_VERSION_SOURCE,
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
        key="odb_hot_water_volume",
        translation_key="odb_hot_water_volume",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:water",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        odb_id=ID_ODB_HOT_WATER_VOLUME,
        available_without_value=True,
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
        key="odb_heating_energy",
        translation_key="odb_heating_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:lightning-bolt",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        odb_id=ID_ODB_HEATING_ENERGY,
        available_without_value=True,
    ),
    StiebelDHESensorEntityDescription(
        key="odb_possible_energy_saving",
        translation_key="odb_possible_energy_saving",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:lightning-bolt-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        odb_id=ID_ODB_POSSIBLE_ENERGY_SAVING,
        available_without_value=True,
    ),
    StiebelDHESensorEntityDescription(
        key="odb_actual_water_saving",
        translation_key="odb_actual_water_saving",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:water-percent",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        odb_id=ID_ODB_ACTUAL_WATER_SAVING,
        available_without_value=True,
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
        timer_activation_odb_id=ID_BRUSH_TIMER_ACTIVATION,
        timer_duration_odb_id=ID_BRUSH_TIMER_DURATION,
        timer_default_duration_minutes=BRUSH_TIMER_DEFAULT_DURATION_MINUTES,
        timer_path=BRUSH_TIMER_PATH,
        timer_property="remainingMilliseconds",
    ),
    StiebelDHESensorEntityDescription(
        key="shower_timer_remaining",
        translation_key="shower_timer_remaining",
        icon="mdi:timer-sand",
        odb_id=ID_SHOWER_TIMER_REMAINING,
        timer_activation_odb_id=ID_SHOWER_TIMER_ACTIVATION,
        timer_duration_odb_id=ID_SHOWER_TIMER_DURATION,
        timer_default_duration_minutes=SHOWER_TIMER_DEFAULT_DURATION_MINUTES,
        timer_path=SHOWER_TIMER_PATH,
        timer_property="remainingMilliseconds",
    ),
    StiebelDHESensorEntityDescription(
        key="wellness_runtime_normalized",
        translation_key="wellness_runtime_normalized",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        icon="mdi:chart-timeline-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        odb_id=ID_WELLNESS_TIME_NORMALIZED,
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
    _unrecorded_attributes = frozenset(
        {
            "chart",
            "activation_rate",
            "possible",
            "real",
            "consumption",
        }
    )

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
            self._base_extra_state_attributes: dict[str, object] = {
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
        if (
            description.available_without_value
            and description.odb_id not in ODB_ZERO_REQUEST_READBACK_IGNORE_IDS
        ):
            raise ValueError(
                f"{description.key} is available without a value but is not "
                "guarded against zero request readbacks"
            )
        filter_values = SENSOR_WRITE_FILTERS.get(description.key)
        if filter_values is None:
            self._min_write_delta = None
            self._max_write_interval_seconds = None
        else:
            self._min_write_delta, self._max_write_interval_seconds = filter_values
        self._last_written_native_value: MeasurementValue = None
        self._last_written_monotonic: float | None = None
        self._last_written_recorded_attributes: dict[str, Any] | None = None
        self._missing_measurement_refresh_task: asyncio.Task[Any] | None = None
        self._missing_measurement_refresh_cancel_registered = False
        self._timer_active = False
        self._timer_countdown_task: asyncio.Task[Any] | None = None
        self._timer_countdown_cancel_registered = False
        self._timer_remaining_base_minutes: float | None = None
        self._timer_remaining_base_monotonic: float | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to DHE measurements and start the persistent session."""
        self.async_on_remove(
            self._client.add_measurement_callback(self._handle_measurement_update)
        )
        self.async_on_remove(
            self._client.add_availability_callback(self._handle_availability_update)
        )

        self._sync_timer_activation_from_client()
        last_value = self._client.last_measurements.get(self.entity_description.odb_id)
        if last_value is not None:
            self._update_extra_state_attributes()
            self._update_timer_remaining_base(last_value)
            self._attr_native_value = self._convert_value(last_value)
            self._attr_available = self._available_from_value(
                self._client_online(),
                self._attr_native_value,
            )
            self._mark_state_written()
            self._schedule_timer_countdown()
        elif self._client.online:
            if self.entity_description.available_without_value:
                self._update_extra_state_attributes()
                self._attr_available = True
                self._mark_state_written(update_value=False)
                self.async_write_ha_state()
            self._schedule_missing_measurement_refresh()

    def _schedule_missing_measurement_refresh(self) -> None:
        """Request a missing value without duplicating concurrent refreshes."""
        if self._attr_native_value is not None:
            return
        self._schedule_measurement_refresh()

    def _schedule_measurement_refresh(self) -> None:
        """Request the current DHE value without duplicating refreshes."""
        task = self._missing_measurement_refresh_task
        if task is not None and not task.done():
            return
        hass = getattr(self, "hass", None)
        if hass is None:
            return

        task = create_background_task(
            hass,
            self._async_refresh_missing_measurement(),
            name=f"stiebel_dhe_connect_refresh_{self.entity_description.key}",
        )
        if task is None:
            return
        self._missing_measurement_refresh_task = task
        if not self._missing_measurement_refresh_cancel_registered:
            self.async_on_remove(self._cancel_missing_measurement_refresh)
            self._missing_measurement_refresh_cancel_registered = True

        def _clear_refresh_task(done_task: asyncio.Task[Any]) -> None:
            if self._missing_measurement_refresh_task is done_task:
                self._missing_measurement_refresh_task = None

        task.add_done_callback(_clear_refresh_task)

    def _cancel_missing_measurement_refresh(self) -> None:
        """Cancel a pending missing-value refresh when the entity is removed."""
        task = self._missing_measurement_refresh_task
        if task is not None and not task.done():
            task.cancel()

    async def _async_refresh_missing_measurement(self) -> None:
        """Request this entity's value when it is enabled after startup."""
        with suppress(DHEError):
            await self._client.request_measurement_refresh(
                odb_id=self.entity_description.odb_id,
                app_command=self._refresh_app_command(),
            )

    def _refresh_app_command(self) -> str | None:
        """Return the app command that can refresh this sensor, if any."""
        if (
            self.entity_description.timer_path is not None
            and self.entity_description.timer_property is not None
        ):
            return (
                f"get:{self.entity_description.timer_path}:"
                f"{self.entity_description.timer_property}"
            )
        source_command = self.entity_description.source_command
        if source_command is None or not source_command.startswith("set:"):
            return None
        if source_command.endswith(":*"):
            return None
        return source_command.replace("set:", "get:", 1)

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

        if (
            not self.entity_description.timer_path
            and self.entity_description.key != "last_usage_time"
        ):
            return value

        return format_minutes_duration(value)

    def _sync_timer_activation_from_client(self) -> None:
        """Load the latest timer activation state for a timer remaining sensor."""
        activation_id = self.entity_description.timer_activation_odb_id
        if activation_id is None:
            return
        activation = switch_state_from_value(
            self._client.last_measurements.get(activation_id)
        )
        if activation is not None:
            self._timer_active = activation

    def _update_timer_remaining_base(self, value: MeasurementValue) -> None:
        """Store the baseline used for local timer countdown display."""
        if self.entity_description.timer_activation_odb_id is None:
            return
        remaining_minutes = coerce_float(value)
        if remaining_minutes is None:
            self._timer_remaining_base_minutes = None
            self._timer_remaining_base_monotonic = None
            self._cancel_timer_countdown()
            return
        self._timer_remaining_base_minutes = max(0.0, remaining_minutes)
        self._timer_remaining_base_monotonic = time.monotonic()

    def _timer_remaining_minutes(self) -> float | None:
        """Return locally adjusted timer remaining minutes."""
        remaining = self._timer_remaining_base_minutes
        if remaining is None:
            return None
        if not self._timer_active:
            return remaining
        started = self._timer_remaining_base_monotonic
        if started is None:
            return remaining
        elapsed_seconds = max(0.0, time.monotonic() - started)
        return max(0.0, remaining - elapsed_seconds / 60.0)

    def _timer_countdown_native_value(self) -> str | None:
        """Return the formatted local timer countdown value."""
        return format_minutes_duration(self._timer_remaining_minutes())

    def _timer_duration_minutes(self) -> float | None:
        """Return the configured timer duration in minutes."""
        duration_id = self.entity_description.timer_duration_odb_id
        duration = None
        if duration_id is not None:
            duration = coerce_float(self._client.last_measurements.get(duration_id))
        if duration is None:
            duration = self.entity_description.timer_default_duration_minutes
        if duration is None:
            return None
        return max(0.0, duration)

    def _reset_timer_remaining_to_duration(self) -> None:
        """Reset local timer remaining display to the configured duration."""
        duration = self._timer_duration_minutes()
        if duration is None:
            return
        self._timer_active = False
        self._timer_remaining_base_minutes = duration
        self._timer_remaining_base_monotonic = time.monotonic()
        native_value = format_minutes_duration(duration)
        if native_value is None or native_value == self._attr_native_value:
            return
        self._attr_native_value = native_value
        self._attr_available = self._available_from_value(
            self._client_online(),
            self._attr_native_value,
        )
        self._mark_state_written()
        self.async_write_ha_state()

    @callback
    def _handle_timer_activation_update(self, value: MeasurementValue) -> None:
        """Start or stop local countdown when a timer activation changes."""
        activation = switch_state_from_value(value)
        if activation is None:
            activation = False
        if activation:
            if (
                not self._timer_active
                and self._timer_remaining_base_minutes is not None
            ):
                self._timer_remaining_base_monotonic = time.monotonic()
            self._timer_active = True
            if self._timer_remaining_base_minutes is None:
                self._schedule_missing_measurement_refresh()
            self._schedule_timer_countdown()
            return

        if self._timer_active:
            current_remaining = self._timer_remaining_minutes()
            if current_remaining is not None and current_remaining <= 0:
                self._timer_active = False
                self._cancel_timer_countdown()
                self._reset_timer_remaining_to_duration()
                return
            if current_remaining is not None:
                self._timer_remaining_base_minutes = current_remaining
                self._timer_remaining_base_monotonic = time.monotonic()
                self._write_timer_countdown_state()
        self._timer_active = False
        self._cancel_timer_countdown()
        self._schedule_measurement_refresh()

    def _timer_countdown_should_run(self) -> bool:
        """Return whether this entity should keep ticking locally."""
        if not self._timer_active or not self._client_online():
            return False
        remaining = self._timer_remaining_minutes()
        return remaining is not None and remaining > 0

    def _schedule_timer_countdown(self) -> None:
        """Start local second-by-second countdown for active timers."""
        if self.entity_description.timer_activation_odb_id is None:
            return
        if not self._timer_countdown_should_run():
            return
        task = self._timer_countdown_task
        if task is not None and not task.done():
            return
        hass = getattr(self, "hass", None)
        if hass is None:
            return

        task = create_background_task(
            hass,
            self._async_timer_countdown(),
            name=f"stiebel_dhe_connect_timer_countdown_{self.entity_description.key}",
        )
        if task is None:
            return
        self._timer_countdown_task = task
        if not self._timer_countdown_cancel_registered:
            self.async_on_remove(self._cancel_timer_countdown)
            self._timer_countdown_cancel_registered = True

        def _clear_countdown_task(done_task: asyncio.Task[Any]) -> None:
            if self._timer_countdown_task is done_task:
                self._timer_countdown_task = None

        task.add_done_callback(_clear_countdown_task)

    def _cancel_timer_countdown(self) -> None:
        """Cancel the local timer countdown task."""
        task = self._timer_countdown_task
        if task is None:
            return
        if not task.done():
            task.cancel()
        self._timer_countdown_task = None

    async def _async_timer_countdown(self) -> None:
        """Write locally adjusted timer remaining state while a timer runs."""
        while self._timer_active and self._client_online():
            await asyncio.sleep(TIMER_COUNTDOWN_INTERVAL_SECONDS)
            if not self._timer_active or not self._client_online():
                break
            self._write_timer_countdown_state()
            if not self._timer_countdown_should_run():
                self._reset_timer_remaining_to_duration()
                break

    def _write_timer_countdown_state(self) -> None:
        """Write the locally adjusted timer remaining state when it changed."""
        native_value = self._timer_countdown_native_value()
        if native_value is None or native_value == self._attr_native_value:
            return
        self._attr_native_value = native_value
        self._attr_available = self._available_from_value(
            self._client_online(),
            self._attr_native_value,
        )
        self._mark_state_written()
        self.async_write_ha_state()

    def _available_from_value(self, connected: bool, value: MeasurementValue) -> bool:
        """Return whether the sensor should be available for this value."""
        if self.entity_description.available_without_value:
            return bool(connected)
        return value_available(connected, value)

    def _client_online(self) -> bool:
        """Return current client connectivity for availability decisions."""
        return bool(getattr(self._client, "online", True))

    def _update_extra_state_attributes(self) -> None:
        """Update static and dynamic sensor attributes."""
        self._attr_extra_state_attributes = merge_state_attributes(
            self._base_extra_state_attributes,
            self._dynamic_state_attributes(),
        )

    def _dynamic_state_attributes(self) -> dict[str, Any]:
        if self.entity_description.attribute_key is not None:
            return {}
        attributes = self._client.last_measurement_attributes.get(
            self.entity_description.odb_id,
            {},
        )
        if not isinstance(attributes, dict):
            return {}
        return cast(dict[str, Any], attributes)

    def _recorded_state_attributes(self) -> dict[str, Any]:
        """Return state attributes that are visible to the recorder."""
        return {
            key: deepcopy(value)
            for key, value in (self._attr_extra_state_attributes or {}).items()
            if key not in self._unrecorded_attributes
        }

    @callback
    def _handle_measurement_update(self, odb_id: int, value: MeasurementValue) -> None:
        """Handle converted measurement updates from the persistent client."""
        if odb_id == self.entity_description.timer_activation_odb_id:
            self._handle_timer_activation_update(value)
            return
        if odb_id != self.entity_description.odb_id:
            return

        self._update_extra_state_attributes()
        self._update_timer_remaining_base(value)
        recorded_attributes = self._recorded_state_attributes()
        recorded_attributes_changed = (
            recorded_attributes != self._last_written_recorded_attributes
        )
        self._attr_native_value = self._convert_value(value)
        self._attr_available = self._available_from_value(
            self._client_online(),
            self._attr_native_value,
        )
        if not self._should_write_measurement_state(
            self._attr_native_value,
            recorded_attributes_changed=recorded_attributes_changed,
        ):
            self._schedule_timer_countdown()
            return
        self._mark_state_written(recorded_attributes=recorded_attributes)
        self.async_write_ha_state()
        self._schedule_timer_countdown()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        if not available:
            self._cancel_timer_countdown()
        if available:
            self._schedule_missing_measurement_refresh()
            self._schedule_timer_countdown()
        next_available = self._available_from_value(available, self._attr_native_value)
        if self._attr_available == next_available:
            return
        self._attr_available = next_available
        self.async_write_ha_state()

    def _should_write_measurement_state(
        self,
        new_value: MeasurementValue,
        *,
        recorded_attributes_changed: bool = False,
    ) -> bool:
        """Return whether this measurement update should write a new HA state."""
        if recorded_attributes_changed:
            return True
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
        if _crosses_zero_boundary(previous_number, new_number):
            return True
        if abs(new_number - previous_number) >= min_write_delta:
            return True

        last_written = self._last_written_monotonic
        if last_written is None:
            return True
        return (time.monotonic() - last_written) >= max_write_interval_seconds

    def _mark_state_written(
        self,
        *,
        recorded_attributes: dict[str, Any] | None = None,
        update_value: bool = True,
    ) -> None:
        """Remember the HA state snapshot last written by this entity."""
        if update_value:
            self._last_written_native_value = self._attr_native_value
        self._last_written_monotonic = time.monotonic()
        self._last_written_recorded_attributes = (
            recorded_attributes
            if recorded_attributes is not None
            else self._recorded_state_attributes()
        )


def _crosses_zero_boundary(previous_number: float, new_number: float) -> bool:
    """Return true when a filtered sensor changes between idle zero and active."""
    return (previous_number == 0.0) != (new_number == 0.0)
