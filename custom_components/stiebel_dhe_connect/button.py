"""Button platform for Stiebel DHE Connect."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import (
    BRUSH_TIMER_PATH,
    DHEClient,
    DHEError,
    ID_BRUSH_TIMER_ACTIVATION,
    ID_SHOWER_TIMER_ACTIVATION,
    MeasurementValue,
    SHOWER_TIMER_PATH,
    TEMPERATURE_MEMORY_SLOT_MEASUREMENTS,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class StiebelDHEButtonEntityDescription(ButtonEntityDescription):
    """Describe a DHE action button."""

    method: str
    method_args: tuple[Any, ...] = ()
    availability_measurement_id: int | None = None
    timer_path: str | None = None
    timer_property: str | None = None
    extra_state_attributes: dict[str, Any] | None = None


STATIC_BUTTON_DESCRIPTIONS: tuple[StiebelDHEButtonEntityDescription, ...] = (
    StiebelDHEButtonEntityDescription(
        key="reset_brush_timer",
        translation_key="reset_brush_timer",
        method="reset_brush_timer",
        icon="mdi:toothbrush",
        availability_measurement_id=ID_BRUSH_TIMER_ACTIVATION,
        timer_path=BRUSH_TIMER_PATH,
        timer_property="reset",
    ),
    StiebelDHEButtonEntityDescription(
        key="reset_shower_timer",
        translation_key="reset_shower_timer",
        method="reset_shower_timer",
        icon="mdi:shower-head",
        availability_measurement_id=ID_SHOWER_TIMER_ACTIVATION,
        timer_path=SHOWER_TIMER_PATH,
        timer_property="reset",
    ),
)

TEMPERATURE_MEMORY_MEASUREMENT_SLOTS = {
    measurement_id: slot for slot, measurement_id in TEMPERATURE_MEMORY_SLOT_MEASUREMENTS.items()
}


def _temperature_memory_button_descriptions(
    slot: int,
    measurement_id: int,
) -> tuple[StiebelDHEButtonEntityDescription, ...]:
    icon = f"mdi:numeric-{slot}-box-outline" if slot < 10 else "mdi:counter"
    descriptions = [
        StiebelDHEButtonEntityDescription(
            key=f"temperature_memory_{slot}",
            translation_key=f"temperature_memory_{slot}",
            method="press_temperature_memory",
            method_args=(slot,),
            icon=icon,
            availability_measurement_id=measurement_id,
            extra_state_attributes={
                "temperature_memory_slot": slot,
                "temperature_memory_id": slot - 1,
                "odb_id": 66,
            },
        ),
    ]
    if slot > 2:
        descriptions.append(
            StiebelDHEButtonEntityDescription(
                key=f"delete_temperature_memory_{slot}",
                translation_key=f"delete_temperature_memory_{slot}",
                method="delete_temperature_memory",
                method_args=(slot,),
                icon="mdi:trash-can-outline",
                availability_measurement_id=measurement_id,
                extra_state_attributes={
                    "temperature_memory_slot": slot,
                    "temperature_memory_id": slot - 1,
                    "temperature_memory_operation": "delete",
                },
            )
        )
    return tuple(descriptions)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DHE buttons from a config entry."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    client: DHEClient = runtime.client
    added_memory_buttons: dict[int, tuple[StiebelDHEButton, ...]] = {}

    def add_memory_buttons(measurement_id: int) -> None:
        if measurement_id in added_memory_buttons:
            return
        slot = TEMPERATURE_MEMORY_MEASUREMENT_SLOTS.get(measurement_id)
        if slot is None:
            return
        entities = tuple(
            StiebelDHEButton(
                entry_id=entry.entry_id,
                name=runtime.name,
                client=client,
                description=description,
            )
            for description in _temperature_memory_button_descriptions(slot, measurement_id)
        )
        added_memory_buttons[measurement_id] = entities
        async_add_entities(list(entities))

    async def remove_memory_buttons(measurement_id: int) -> None:
        entities = added_memory_buttons.pop(measurement_id, ())
        for entity in entities:
            await entity.async_remove()
        slot = TEMPERATURE_MEMORY_MEASUREMENT_SLOTS.get(measurement_id)
        if slot is None:
            return
        registry = er.async_get(hass)
        for description in _temperature_memory_button_descriptions(slot, measurement_id):
            entity_id = registry.async_get_entity_id(
                "button",
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
            hass.async_create_task(remove_memory_buttons(odb_id))
            return
        add_memory_buttons(odb_id)

    async_add_entities(
        [
            StiebelDHEButton(
                entry_id=entry.entry_id,
                name=runtime.name,
                client=client,
                description=description,
            )
            for description in STATIC_BUTTON_DESCRIPTIONS
        ]
    )
    registry = er.async_get(hass)
    for slot in (1, 2):
        entity_id = registry.async_get_entity_id(
            "button",
            DOMAIN,
            f"stiebel_dhe_connect_{entry.entry_id}_delete_temperature_memory_{slot}",
        )
        if entity_id is not None:
            registry.async_remove(entity_id)

    entry.async_on_unload(client.add_measurement_callback(handle_temperature_memory_update))


class StiebelDHEButton(ButtonEntity):
    """DHE command button."""

    entity_description: StiebelDHEButtonEntityDescription
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry_id: str,
        name: str,
        client: DHEClient,
        description: StiebelDHEButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        self.entity_description = description
        self._attr_translation_key = description.translation_key
        self._attr_icon = description.icon
        self._attr_unique_id = f"stiebel_dhe_connect_{entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, client.host)},
            "manufacturer": "STIEBEL ELTRON",
            "model": "DHE Connect",
            "name": name,
        }
        extra_state_attributes = dict(description.extra_state_attributes or {})
        if description.timer_path is not None:
            extra_state_attributes["timer_path"] = description.timer_path
        if description.timer_property is not None:
            extra_state_attributes["timer_property"] = description.timer_property
        self._attr_extra_state_attributes = extra_state_attributes or None
        self._client = client
        self._attr_available = False
        self._has_seen_availability_state = False

    async def async_added_to_hass(self) -> None:
        """Subscribe to availability updates and start the persistent session."""
        self.async_on_remove(
            self._client.add_measurement_callback(self._handle_measurement_update)
        )
        self.async_on_remove(
            self._client.add_availability_callback(self._handle_availability_update)
        )
        availability_measurement_id = self.entity_description.availability_measurement_id
        if (
            availability_measurement_id is not None
            and self._client.last_measurements.get(availability_measurement_id) is not None
        ):
            self._has_seen_availability_state = True
        self._attr_available = self._button_available(self._client.available)

    @callback
    def _handle_measurement_update(self, odb_id: int, value: MeasurementValue) -> None:
        """Track whether the heater has delivered a related state."""
        availability_measurement_id = self.entity_description.availability_measurement_id
        if availability_measurement_id is None or odb_id != availability_measurement_id:
            return
        self._has_seen_availability_state = value is not None
        self._attr_available = self._button_available(self._client.available)
        self.async_write_ha_state()

    async def async_press(self) -> None:
        """Execute the DHE button action."""
        try:
            method = getattr(self._client, self.entity_description.method)
            await method(*self.entity_description.method_args)
        except DHEError as err:
            _LOGGER.error("Could not execute DHE button %s: %s", self.entity_description.key, err)
            raise

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = self._button_available(available)
        self.async_write_ha_state()

    def _button_available(self, client_available: bool) -> bool:
        if self.entity_description.availability_measurement_id is None:
            return client_available
        return client_available and self._has_seen_availability_state
