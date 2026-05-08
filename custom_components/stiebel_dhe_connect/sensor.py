"""Sensor platform for Stiebel DHE Connect."""

from __future__ import annotations

from dataclasses import dataclass

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
    ID_BRUSH_TIMER_REMAINING,
    ID_CONFIGURED_POWER,
    ID_ENERGY_CONSUMPTION_WEEK,
    ID_ENERGY_CONSUMPTION_YEAR,
    ID_ENERGY_CONSUMPTION_YEARS,
    ID_DEVICE_INFO,
    ID_LAST_USAGE_COST,
    ID_LAST_USAGE_ENERGY,
    ID_LAST_USAGE_TIME,
    ID_LAST_USAGE_WATER,
    ID_POWER,
    ID_SAVING_MONITOR_ACTIVATION_RATE,
    ID_SAVING_MONITOR_CO2,
    ID_SAVING_MONITOR_ENERGY,
    ID_SAVING_MONITOR_WATER,
    ID_SHOWER_TIMER_REMAINING,
    ID_UNHANDLED_ODB_VALUES,
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
    timer_path: str | None = None
    timer_property: str | None = None
    source_command: str | None = None
    period: str | None = None


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
        icon="mdi:water-check",
        odb_id=ID_LAST_USAGE_WATER,
        source_command="set:ste.app.consumption:lastUsage",
    ),
    StiebelDHESensorEntityDescription(
        key="last_usage_energy",
        translation_key="last_usage_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:lightning-bolt",
        odb_id=ID_LAST_USAGE_ENERGY,
        source_command="set:ste.app.consumption:lastUsage",
    ),
    StiebelDHESensorEntityDescription(
        key="last_usage_time",
        translation_key="last_usage_time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-outline",
        odb_id=ID_LAST_USAGE_TIME,
        source_command="set:ste.app.consumption:lastUsage",
    ),
    StiebelDHESensorEntityDescription(
        key="last_usage_cost",
        translation_key="last_usage_cost",
        native_unit_of_measurement="EUR",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash",
        odb_id=ID_LAST_USAGE_COST,
        source_command="set:ste.app.consumption:lastUsage",
    ),
    StiebelDHESensorEntityDescription(
        key="saving_monitor_water",
        translation_key="saving_monitor_water",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:water-percent",
        odb_id=ID_SAVING_MONITOR_WATER,
        source_command="set:ste.app.savingMonitor:consumption",
    ),
    StiebelDHESensorEntityDescription(
        key="saving_monitor_energy",
        translation_key="saving_monitor_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
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
        icon="mdi:leaf-circle",
        odb_id=ID_SAVING_MONITOR_ACTIVATION_RATE,
        source_command="set:ste.app.savingMonitor:ActivationRate",
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
        key="unhandled_odb_values",
        translation_key="unhandled_odb_values",
        icon="mdi:database-search",
        entity_category=EntityCategory.DIAGNOSTIC,
        odb_id=ID_UNHANDLED_ODB_VALUES,
        source_command="ste.common.odb:value",
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
            self._attr_native_value = self._convert_value(last_value)
            self._attr_available = True
            self._update_extra_state_attributes()

    def _convert_value(self, value: MeasurementValue) -> MeasurementValue:
        """Convert the raw client value for display."""
        if not self.entity_description.timer_path:
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

        self._attr_native_value = self._convert_value(value)
        self._attr_available = True
        self._update_extra_state_attributes()
        self.async_write_ha_state()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = available or self._attr_native_value is not None
        self.async_write_ha_state()


class StiebelDHEReconnectCountSensor(SensorEntity):
    """DHE reconnect count diagnostic sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
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
