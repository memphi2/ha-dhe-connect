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
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import (
    BRUSH_TIMER_PATH,
    DHEClient,
    DHEError,
    ID_BATH_FILL_TARGET_VOLUME,
    ID_BRUSH_TIMER_DURATION,
    ID_ECO_FLOW_LIMIT,
    ID_MAX_TEMPERATURE,
    ID_SHOWER_TIMER_DURATION,
    MeasurementValue,
    SHOWER_TIMER_PATH,
    TEMPERATURE_MEMORY_SLOT_MEASUREMENTS,
)
from .entity_helpers import StiebelDHEEntityMixin
from .entity_state_helpers import (
    clamp_duration_seconds,
    coerce_float,
    format_minutes_duration,
    minutes_to_seconds,
    seconds_to_minutes,
    value_available,
)
from .runtime_helpers import get_runtime_data

_LOGGER = logging.getLogger(__name__)

TIMER_DURATION_MIN_SECONDS = 60
TIMER_DURATION_MAX_SECONDS = 1200


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
        native_min_value=20.0,
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
        key="brush_timer_duration",
        translation_key="brush_timer_duration",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        icon="mdi:toothbrush",
        native_min_value=TIMER_DURATION_MIN_SECONDS,
        native_max_value=TIMER_DURATION_MAX_SECONDS,
        native_step=1,
        mode=NumberMode.BOX,
        odb_id=ID_BRUSH_TIMER_DURATION,
        timer_path=BRUSH_TIMER_PATH,
        timer_property="durationMilliseconds",
    ),
    StiebelDHENumberEntityDescription(
        key="shower_timer_duration",
        translation_key="shower_timer_duration",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        icon="mdi:timer-edit",
        native_min_value=TIMER_DURATION_MIN_SECONDS,
        native_max_value=TIMER_DURATION_MAX_SECONDS,
        native_step=1,
        mode=NumberMode.BOX,
        odb_id=ID_SHOWER_TIMER_DURATION,
        timer_path=SHOWER_TIMER_PATH,
        timer_property="durationMilliseconds",
    ),
)


TEMPERATURE_MEMORY_MEASUREMENT_SLOTS = {
    measurement_id: slot for slot, measurement_id in TEMPERATURE_MEMORY_SLOT_MEASUREMENTS.items()
}


def _temperature_memory_enabled_default(slot: int) -> bool:
    """Return whether a temperature memory slot is enabled by default."""
    return slot <= 2


def _temperature_memory_number_description(
    slot: int,
    measurement_id: int,
) -> StiebelDHENumberEntityDescription:
    """Create the number description for a temperature memory slot."""
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
        entity_registry_enabled_default=_temperature_memory_enabled_default(slot),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DHE number entities from a config entry."""
    runtime = get_runtime_data(hass, entry)
    client: DHEClient = runtime.client

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
        + [
            StiebelDHENumber(
                entry_id=entry.entry_id,
                name=runtime.name,
                client=client,
                description=_temperature_memory_number_description(slot, measurement_id),
            )
            for measurement_id, slot in sorted(
                TEMPERATURE_MEMORY_MEASUREMENT_SLOTS.items(), key=lambda item: item[1]
            )
        ]
    )


class StiebelDHENumber(StiebelDHEEntityMixin, RestoreNumber):
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
        self._init_dhe_entity(
            entry_id=entry_id,
            key=description.key,
            name=name,
            client=client,
        )
        self._attr_entity_registry_enabled_default = (
            description.entity_registry_enabled_default
        )
        if description.timer_path:
            base_attributes = {
                "timer_path": description.timer_path,
                "timer_property": description.timer_property,
            }
        elif description.temperature_memory_slot is not None:
            base_attributes = {
                "temperature_memory_slot": description.temperature_memory_slot,
            }
        else:
            base_attributes = {"odb_id": description.odb_id}
        self._base_extra_state_attributes = base_attributes
        self._attr_extra_state_attributes = dict(base_attributes)
        self._attr_available = False
        self._attr_native_value: float | None = None
        self._timer_duration_seconds: int | None = None

    @property
    def _is_timer_duration(self) -> bool:
        """Return whether this number controls a timer duration."""
        return self.entity_description.timer_property == "durationMilliseconds"

    def _client_value_to_native(self, value: object) -> float | None:
        """Convert the client measurement value to the HA number value."""
        if self._is_timer_duration:
            total_seconds = self._timer_total_seconds_from_client(value)
            if total_seconds is None:
                return None
            self._timer_duration_seconds = total_seconds
            return total_seconds
        return coerce_float(value)

    def _native_value_to_client(self, value: object) -> float | None:
        """Convert the HA number value to the client write value."""
        if self._is_timer_duration:
            total_seconds = self._timer_total_seconds_for_write(value)
            if total_seconds is None:
                return None
            return seconds_to_minutes(total_seconds)
        return coerce_float(value)

    def _restore_native_value(self, value: object) -> float | None:
        """Return a restored native value, accepting old minute-based timer state."""
        restored_value = coerce_float(value)
        if restored_value is None:
            return None
        if self._is_timer_duration:
            return self._restore_timer_native_value(restored_value)
        return restored_value

    def _restore_timer_native_value(self, restored_value: float) -> float | None:
        """Return seconds, accepting old minute-based timer state."""
        candidate = (
            minutes_to_seconds(restored_value)
            if 0 < restored_value < TIMER_DURATION_MIN_SECONDS
            else restored_value
        )
        total_seconds = clamp_duration_seconds(
            candidate,
            minimum=TIMER_DURATION_MIN_SECONDS,
            maximum=TIMER_DURATION_MAX_SECONDS,
        )
        if total_seconds is None:
            return None
        self._timer_duration_seconds = total_seconds
        return total_seconds

    def _timer_total_seconds_from_client(self, value: object) -> int | None:
        """Return whole timer seconds from the client minute value."""
        return clamp_duration_seconds(
            minutes_to_seconds(value),
            minimum=TIMER_DURATION_MIN_SECONDS,
            maximum=TIMER_DURATION_MAX_SECONDS,
        )

    def _timer_total_seconds_for_write(self, value: object) -> int | None:
        """Return the requested whole-second timer duration."""
        return clamp_duration_seconds(
            value,
            minimum=TIMER_DURATION_MIN_SECONDS,
            maximum=TIMER_DURATION_MAX_SECONDS,
        )

    def _update_extra_state_attributes(self) -> None:
        """Refresh static and display-only attributes."""
        attributes = dict(self._base_extra_state_attributes)
        if self._is_timer_duration and self._timer_duration_seconds is not None:
            minutes_value = seconds_to_minutes(self._timer_duration_seconds)
            display_value = format_minutes_duration(minutes_value)
            if display_value is not None:
                attributes["duration"] = display_value
                attributes["duration_seconds"] = self._timer_duration_seconds
        self._attr_extra_state_attributes = attributes

    async def async_added_to_hass(self) -> None:
        """Subscribe to DHE updates and start the persistent session."""
        self.async_on_remove(
            self._client.add_measurement_callback(self._handle_measurement_update)
        )
        self.async_on_remove(
            self._client.add_availability_callback(self._handle_availability_update)
        )

        last_value = self._client.last_measurements.get(self.entity_description.odb_id)
        native_value = self._client_value_to_native(last_value)
        if native_value is not None:
            self._attr_native_value = native_value
            self._attr_available = True
        else:
            last_number_data = await self.async_get_last_number_data()
            restored_value = self._restore_native_value(
                last_number_data.native_value if last_number_data else None
            )
            if restored_value is not None:
                self._attr_native_value = restored_value
                self._attr_available = True
        self._update_extra_state_attributes()

    async def async_set_native_value(self, value: float) -> None:
        """Set the DHE ODB value and update state from confirmed writeback."""
        client_value = self._native_value_to_client(value)
        if client_value is None:
            return

        try:
            if self.entity_description.odb_id == ID_BATH_FILL_TARGET_VOLUME:
                confirmed = await self._client.set_bath_fill_target_volume(client_value)
            elif self.entity_description.odb_id == ID_MAX_TEMPERATURE:
                confirmed = await self._client.set_maximum_temperature(client_value)
            elif self.entity_description.odb_id == ID_ECO_FLOW_LIMIT:
                confirmed = await self._client.set_eco_flow_limit(client_value)
            elif self.entity_description.odb_id == ID_BRUSH_TIMER_DURATION:
                confirmed = await self._client.set_brush_timer_duration_minutes(
                    client_value
                )
            elif self.entity_description.odb_id == ID_SHOWER_TIMER_DURATION:
                confirmed = await self._client.set_shower_timer_duration_minutes(
                    client_value
                )
            elif self.entity_description.temperature_memory_slot is not None:
                confirmed = await self._client.set_temperature_memory(
                    self.entity_description.temperature_memory_slot,
                    client_value,
                )
            else:
                confirmed = await self._client.write_odb_value(
                    self.entity_description.odb_id,
                    client_value,
                )
        except DHEError as err:
            self._attr_available = self._attr_native_value is not None
            self.async_write_ha_state()
            _LOGGER.error("Could not set DHE number %s: %s", self.entity_description.key, err)
            raise

        self._attr_native_value = self._client_value_to_native(confirmed)
        self._attr_available = True
        self._update_extra_state_attributes()
        self.async_write_ha_state()

    @callback
    def _handle_measurement_update(self, odb_id: int, value: MeasurementValue) -> None:
        """Handle converted ODB value updates from the persistent client."""
        if odb_id != self.entity_description.odb_id:
            return
        native_value = self._client_value_to_native(value)
        if native_value is None:
            self._attr_native_value = None
            self._attr_available = (
                self._client.available
                if self.entity_description.temperature_memory_slot is not None
                else False
            )
            self._update_extra_state_attributes()
            self.async_write_ha_state()
            return

        self._attr_native_value = native_value
        self._attr_available = True
        self._update_extra_state_attributes()
        self.async_write_ha_state()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        if self.entity_description.temperature_memory_slot is not None:
            self._attr_available = available
            self.async_write_ha_state()
            return
        self._attr_available = value_available(available, self._attr_native_value)
        self.async_write_ha_state()
