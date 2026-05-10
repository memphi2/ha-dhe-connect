"""Number platform for Stiebel DHE Connect."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntityDescription,
    NumberMode,
    RestoreNumber,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfTime, UnitOfVolume, UnitOfVolumeFlowRate
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import (
    BRUSH_TIMER_PATH,
    DHEClient,
    DHEError,
    ID_BATH_FILL_TARGET_VOLUME,
    ID_BRUSH_TIMER_DURATION,
    ID_CO2_EMISSION,
    ID_ECO_FLOW_LIMIT,
    ID_ELECTRICITY_PRICE,
    ID_MAX_TEMPERATURE,
    ID_SHOWER_TIMER_DURATION,
    ID_WATER_PRICE,
    MeasurementValue,
    SHOWER_TIMER_PATH,
    TEMPERATURE_MEMORY_SLOT_MEASUREMENTS,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class StiebelDHENumberEntityDescription(NumberEntityDescription):
    """Describe a writable DHE number."""

    odb_id: int
    timer_path: str | None = None
    timer_property: str | None = None
    temperature_memory_slot: int | None = None


STATIC_NUMBER_DESCRIPTIONS: tuple[StiebelDHENumberEntityDescription, ...] = (
    StiebelDHENumberEntityDescription(
        key="bath_fill_target_volume",
        translation_key="bath_fill_target_volume",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=NumberDeviceClass.VOLUME,
        icon="mdi:bathtub",
        native_min_value=1.0,
        native_max_value=300.0,
        native_step=1.0,
        odb_id=ID_BATH_FILL_TARGET_VOLUME,
    ),
    StiebelDHENumberEntityDescription(
        key="maximum_temperature",
        translation_key="maximum_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        icon="mdi:thermometer-high",
        native_min_value=30.0,
        native_max_value=50.0,
        native_step=0.5,
        odb_id=ID_MAX_TEMPERATURE,
    ),
    StiebelDHENumberEntityDescription(
        key="eco_flow_limit",
        translation_key="eco_flow_limit",
        native_unit_of_measurement=UnitOfVolumeFlowRate.LITERS_PER_MINUTE,
        device_class=NumberDeviceClass.VOLUME_FLOW_RATE,
        icon="mdi:water-pump",
        native_min_value=6.0,
        native_max_value=8.0,
        native_step=1.0,
        odb_id=ID_ECO_FLOW_LIMIT,
    ),
    StiebelDHENumberEntityDescription(
        key="electricity_price",
        translation_key="electricity_price",
        native_unit_of_measurement="EUR/kWh",
        icon="mdi:currency-eur",
        native_min_value=0.0,
        native_max_value=9.99,
        native_step=0.01,
        mode=NumberMode.BOX,
        odb_id=ID_ELECTRICITY_PRICE,
        entity_registry_enabled_default=False,
    ),
    StiebelDHENumberEntityDescription(
        key="water_price",
        translation_key="water_price",
        native_unit_of_measurement="EUR/m3",
        icon="mdi:water-percent",
        native_min_value=0.0,
        native_max_value=9.99,
        native_step=0.01,
        mode=NumberMode.BOX,
        odb_id=ID_WATER_PRICE,
        entity_registry_enabled_default=False,
    ),
    StiebelDHENumberEntityDescription(
        key="co2_emission",
        translation_key="co2_emission",
        native_unit_of_measurement="kg/kWh",
        icon="mdi:molecule-co2",
        native_min_value=0.0,
        native_max_value=99.99,
        native_step=0.01,
        mode=NumberMode.BOX,
        odb_id=ID_CO2_EMISSION,
        entity_registry_enabled_default=False,
    ),
    StiebelDHENumberEntityDescription(
        key="brush_timer_duration",
        translation_key="brush_timer_duration",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        icon="mdi:toothbrush",
        native_min_value=1.0,
        native_max_value=20.0,
        native_step=1.0,
        mode=NumberMode.BOX,
        odb_id=ID_BRUSH_TIMER_DURATION,
        timer_path=BRUSH_TIMER_PATH,
        timer_property="durationMilliseconds",
    ),
    StiebelDHENumberEntityDescription(
        key="shower_timer_duration",
        translation_key="shower_timer_duration",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        icon="mdi:timer-edit",
        native_min_value=1.0,
        native_max_value=20.0,
        native_step=1.0,
        mode=NumberMode.BOX,
        odb_id=ID_SHOWER_TIMER_DURATION,
        timer_path=SHOWER_TIMER_PATH,
        timer_property="durationMilliseconds",
    ),
)


TEMPERATURE_MEMORY_MEASUREMENT_SLOTS = {
    measurement_id: slot for slot, measurement_id in TEMPERATURE_MEMORY_SLOT_MEASUREMENTS.items()
}


def _temperature_memory_number_description(
    slot: int,
    measurement_id: int,
) -> StiebelDHENumberEntityDescription:
    """Create the number description for a reported temperature memory slot."""
    return StiebelDHENumberEntityDescription(
        key=f"temperature_memory_{slot}_temperature",
        translation_key=f"temperature_memory_{slot}_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        icon=f"mdi:numeric-{slot}-box-outline" if slot < 10 else "mdi:counter",
        native_min_value=20.0,
        native_max_value=60.0,
        native_step=0.5,
        mode=NumberMode.BOX,
        odb_id=measurement_id,
        temperature_memory_slot=slot,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DHE number entities from a config entry."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    client: DHEClient = runtime.client
    added_memory_numbers: dict[int, StiebelDHENumber] = {}

    def add_memory_number(measurement_id: int) -> None:
        if measurement_id in added_memory_numbers:
            return
        slot = TEMPERATURE_MEMORY_MEASUREMENT_SLOTS.get(measurement_id)
        if slot is None:
            return
        entity = StiebelDHENumber(
            entry_id=entry.entry_id,
            name=runtime.name,
            client=client,
            description=_temperature_memory_number_description(slot, measurement_id),
        )
        added_memory_numbers[measurement_id] = entity
        async_add_entities([entity])

    async def remove_memory_number(measurement_id: int) -> None:
        entity = added_memory_numbers.pop(measurement_id, None)
        if entity is not None:
            await entity.async_remove()
        slot = TEMPERATURE_MEMORY_MEASUREMENT_SLOTS.get(measurement_id)
        if slot is None:
            return
        registry = er.async_get(hass)
        description = _temperature_memory_number_description(slot, measurement_id)
        entity_id = registry.async_get_entity_id(
            "number",
            DOMAIN,
            f"stiebel_dhe_connect_{entry.entry_id}_{description.key}",
        )
        if entity_id is not None:
            registry.async_remove(entity_id)

    @callback
    def handle_temperature_memory_update(odb_id: int, value: MeasurementValue) -> None:
        if odb_id not in TEMPERATURE_MEMORY_MEASUREMENT_SLOTS:
            return
        if value is None:
            hass.async_create_task(remove_memory_number(odb_id))
            return
        add_memory_number(odb_id)

    async_add_entities(
        [
            StiebelDHENumber(
                entry_id=entry.entry_id,
                name=runtime.name,
                client=client,
                description=description,
            )
            for description in STATIC_NUMBER_DESCRIPTIONS
        ]
    )
    entry.async_on_unload(client.add_measurement_callback(handle_temperature_memory_update))


class StiebelDHENumber(RestoreNumber):
    """Writable DHE setting represented as a Home Assistant number."""

    entity_description: StiebelDHENumberEntityDescription
    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry_id: str,
        name: str,
        client: DHEClient,
        description: StiebelDHENumberEntityDescription,
    ) -> None:
        """Initialize the number entity."""
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
            self._attr_extra_state_attributes = {
                "timer_path": description.timer_path,
                "timer_property": description.timer_property,
            }
        elif description.temperature_memory_slot is not None:
            self._attr_extra_state_attributes = {
                "temperature_memory_slot": description.temperature_memory_slot,
            }
        else:
            self._attr_extra_state_attributes = {"odb_id": description.odb_id}
        self._client = client
        self._attr_available = False
        self._attr_native_value: float | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to DHE updates and start the persistent session."""
        self.async_on_remove(
            self._client.add_measurement_callback(self._handle_measurement_update)
        )
        self.async_on_remove(
            self._client.add_availability_callback(self._handle_availability_update)
        )

        last_value = self._client.last_measurements.get(self.entity_description.odb_id)
        if last_value is not None and not isinstance(last_value, bool):
            self._attr_native_value = float(last_value)
            self._attr_available = True
        else:
            last_number_data = await self.async_get_last_number_data()
            if last_number_data and last_number_data.native_value is not None:
                self._attr_native_value = float(last_number_data.native_value)
                self._attr_available = True

    async def async_set_native_value(self, value: float) -> None:
        """Set the DHE ODB value and update state from confirmed writeback."""
        try:
            if self.entity_description.odb_id == ID_BATH_FILL_TARGET_VOLUME:
                confirmed = await self._client.set_bath_fill_target_volume(value)
            elif self.entity_description.odb_id == ID_MAX_TEMPERATURE:
                confirmed = await self._client.set_maximum_temperature(value)
            elif self.entity_description.odb_id == ID_ECO_FLOW_LIMIT:
                confirmed = await self._client.set_eco_flow_limit(value)
            elif self.entity_description.odb_id == ID_ELECTRICITY_PRICE:
                confirmed = await self._client.set_electricity_price(value)
            elif self.entity_description.odb_id == ID_WATER_PRICE:
                confirmed = await self._client.set_water_price(value)
            elif self.entity_description.odb_id == ID_CO2_EMISSION:
                confirmed = await self._client.set_co2_emission(value)
            elif self.entity_description.odb_id == ID_BRUSH_TIMER_DURATION:
                confirmed = await self._client.set_brush_timer_duration_minutes(value)
            elif self.entity_description.odb_id == ID_SHOWER_TIMER_DURATION:
                confirmed = await self._client.set_shower_timer_duration_minutes(value)
            elif self.entity_description.temperature_memory_slot is not None:
                confirmed = await self._client.set_temperature_memory(
                    self.entity_description.temperature_memory_slot,
                    value,
                )
            else:
                confirmed = await self._client.write_odb_value(
                    self.entity_description.odb_id,
                    value,
                )
        except DHEError as err:
            self._attr_available = self._attr_native_value is not None
            self.async_write_ha_state()
            _LOGGER.error("Could not set DHE number %s: %s", self.entity_description.key, err)
            raise

        self._attr_native_value = float(confirmed)
        self._attr_available = True
        self.async_write_ha_state()

    @callback
    def _handle_measurement_update(self, odb_id: int, value: MeasurementValue) -> None:
        """Handle converted ODB value updates from the persistent client."""
        if odb_id != self.entity_description.odb_id or isinstance(value, bool):
            return
        if value is None:
            self._attr_native_value = None
            self._attr_available = (
                self._client.available
                if self.entity_description.temperature_memory_slot is not None
                else False
            )
            self.async_write_ha_state()
            return

        self._attr_native_value = float(value)
        self._attr_available = True
        self.async_write_ha_state()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        if self.entity_description.temperature_memory_slot is not None:
            self._attr_available = available
            self.async_write_ha_state()
            return
        self._attr_available = available or self._attr_native_value is not None
        self.async_write_ha_state()
