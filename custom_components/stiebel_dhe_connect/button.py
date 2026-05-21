"""Button platform for DHE Connect."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .action_error_helpers import dhe_action_error, raise_if_dhe_unavailable
from .client import DHEClient
from .client_types import DHEError, MeasurementValue
from .entity_helpers import (
    StiebelDHEEntityMixin,
    temperature_memory_enabled_default,
    temperature_memory_icon,
    temperature_memory_measurement_slot_items,
)
from .protocol import (
    BRUSH_TIMER_PATH,
    ID_BRUSH_TIMER_ACTIVATION,
    ID_SHOWER_TIMER_ACTIVATION,
    SHOWER_TIMER_PATH,
    TEMPERATURE_MEMORY_SLOT_MEASUREMENTS,
)
from .runtime_helpers import get_runtime_data

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class StiebelDHEButtonEntityDescription(ButtonEntityDescription):
    """Describe a DHE action button."""

    method: str
    method_args: tuple[Any, ...] = ()
    availability_measurement_id: int | None = None
    timer_path: str | None = None
    timer_property: str | None = None
    extra_state_attributes: dict[str, Any] | None = None
    available_without_connection: bool = False


STATIC_BUTTON_DESCRIPTIONS: tuple[StiebelDHEButtonEntityDescription, ...] = (
    StiebelDHEButtonEntityDescription(
        key="reset_brush_timer",
        translation_key="reset_brush_timer",
        method="reset_brush_timer",
        icon="mdi:toothbrush",
        availability_measurement_id=ID_BRUSH_TIMER_ACTIVATION,
        timer_path=BRUSH_TIMER_PATH,
        timer_property="reset",
        entity_registry_enabled_default=False,
    ),
    StiebelDHEButtonEntityDescription(
        key="reset_shower_timer",
        translation_key="reset_shower_timer",
        method="reset_shower_timer",
        icon="mdi:shower-head",
        availability_measurement_id=ID_SHOWER_TIMER_ACTIVATION,
        timer_path=SHOWER_TIMER_PATH,
        timer_property="reset",
        entity_registry_enabled_default=False,
    ),
    StiebelDHEButtonEntityDescription(
        key="repair_pairing",
        translation_key="repair_pairing",
        method="repair_pairing",
        icon="mdi:refresh",
        entity_registry_enabled_default=False,
        available_without_connection=True,
        extra_state_attributes={
            "pairing_action": "delete_token_and_reconnect",
        },
    ),
    StiebelDHEButtonEntityDescription(
        key="disconnect_radio_pairing",
        translation_key="disconnect_radio_pairing",
        method="disconnect_radio_pairing",
        icon="mdi:speaker-bluetooth",
        entity_registry_enabled_default=False,
        extra_state_attributes={
            "radio_path": "ste.app.radio",
            "radio_property": "paired",
            "radio_value": False,
        },
    ),
)

TEMPERATURE_MEMORY_MEASUREMENT_SLOT_ITEMS = temperature_memory_measurement_slot_items(
    TEMPERATURE_MEMORY_SLOT_MEASUREMENTS
)


def _temperature_memory_button_descriptions(
    slot: int,
    measurement_id: int,
) -> tuple[StiebelDHEButtonEntityDescription, ...]:
    icon = temperature_memory_icon(slot)
    descriptions = [
        StiebelDHEButtonEntityDescription(
            key=f"temperature_memory_{slot}",
            translation_key=f"temperature_memory_{slot}",
            method="press_temperature_memory",
            method_args=(slot,),
            icon=icon,
            availability_measurement_id=measurement_id,
            entity_registry_enabled_default=temperature_memory_enabled_default(slot),
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
                entity_registry_enabled_default=False,
                extra_state_attributes={
                    "temperature_memory_slot": slot,
                    "temperature_memory_id": slot - 1,
                    "temperature_memory_operation": "delete",
                },
            )
        )
    return tuple(descriptions)


def _button_available(
    description: StiebelDHEButtonEntityDescription,
    *,
    client_available: bool,
    has_seen_availability_state: bool,
) -> bool:
    """Return whether a button should be available in Home Assistant."""
    if description.available_without_connection:
        return True
    if description.availability_measurement_id is None:
        return client_available
    return client_available and has_seen_availability_state


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DHE buttons from a config entry."""
    runtime = get_runtime_data(hass, entry)
    client: DHEClient = runtime.client

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
        + [
            StiebelDHEButton(
                entry_id=entry.entry_id,
                name=runtime.name,
                client=client,
                description=description,
            )
            for measurement_id, slot in TEMPERATURE_MEMORY_MEASUREMENT_SLOT_ITEMS
            for description in _temperature_memory_button_descriptions(slot, measurement_id)
        ]
    )

class StiebelDHEButton(StiebelDHEEntityMixin, ButtonEntity):
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
        self._attr_entity_registry_enabled_default = (
            description.entity_registry_enabled_default
        )
        self._init_dhe_entity(
            entry_id=entry_id,
            key=description.key,
            name=name,
            client=client,
        )
        extra_state_attributes = dict(description.extra_state_attributes or {})
        if description.timer_path is not None:
            extra_state_attributes["timer_path"] = description.timer_path
        if description.timer_property is not None:
            extra_state_attributes["timer_property"] = description.timer_property
        self._attr_extra_state_attributes = extra_state_attributes or None
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
            if not self.entity_description.available_without_connection:
                raise_if_dhe_unavailable(
                    self._client,
                    f"DHE is unavailable; cannot execute button {self.entity_description.key}",
                )
            method = getattr(self._client, self.entity_description.method)
            await method(*self.entity_description.method_args)
        except DHEError as err:
            raise dhe_action_error(
                f"Could not execute DHE button {self.entity_description.key}",
                err,
            ) from err

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = self._button_available(available)
        self.async_write_ha_state()

    def _button_available(self, client_available: bool) -> bool:
        return _button_available(
            self.entity_description,
            client_available=client_available,
            has_seen_availability_state=self._has_seen_availability_state,
        )
