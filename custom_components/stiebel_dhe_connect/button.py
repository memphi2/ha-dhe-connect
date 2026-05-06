"""Button platform for Stiebel DHE Connect."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import (
    BRUSH_TIMER_PATH,
    DHEClient,
    DHEError,
    ID_BATH_FILL_ACTIVE,
    ID_BRUSH_TIMER_ACTIVATION,
    ID_SHOWER_TIMER_ACTIVATION,
    ODBValue,
    SHOWER_TIMER_PATH,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class StiebelDHEButtonEntityDescription(ButtonEntityDescription):
    """Describe a DHE action button."""

    method: str
    icon: str
    method_arg: bool | None = None
    availability_measurement_id: int | None = None
    timer_path: str | None = None
    timer_property: str | None = None


BUTTON_DESCRIPTIONS: tuple[StiebelDHEButtonEntityDescription, ...] = (
    StiebelDHEButtonEntityDescription(
        key="start_bath_fill",
        translation_key="start_bath_fill",
        method="start_bath_fill",
        icon="mdi:bathtub",
        availability_measurement_id=ID_BATH_FILL_ACTIVE,
    ),
    StiebelDHEButtonEntityDescription(
        key="stop_bath_fill",
        translation_key="stop_bath_fill",
        method="stop_bath_fill",
        icon="mdi:stop-circle-outline",
        availability_measurement_id=ID_BATH_FILL_ACTIVE,
    ),
    StiebelDHEButtonEntityDescription(
        key="start_brush_timer",
        translation_key="start_brush_timer",
        method="set_brush_timer_activation",
        method_arg=True,
        icon="mdi:toothbrush",
        availability_measurement_id=ID_BRUSH_TIMER_ACTIVATION,
        timer_path=BRUSH_TIMER_PATH,
        timer_property="activation",
    ),
    StiebelDHEButtonEntityDescription(
        key="start_shower_timer",
        translation_key="start_shower_timer",
        method="set_shower_timer_activation",
        method_arg=True,
        icon="mdi:shower-head",
        availability_measurement_id=ID_SHOWER_TIMER_ACTIVATION,
        timer_path=SHOWER_TIMER_PATH,
        timer_property="activation",
    ),
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DHE buttons from a config entry."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            StiebelDHEButton(
                entry_id=entry.entry_id,
                name=runtime.name,
                client=runtime.client,
                description=description,
            )
            for description in BUTTON_DESCRIPTIONS
        ]
    )


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
        if description.timer_path:
            self._attr_extra_state_attributes = {
                "timer_path": description.timer_path,
                "timer_property": description.timer_property,
            }
        else:
            self._attr_extra_state_attributes = {"odb_id": ID_BATH_FILL_ACTIVE}
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
            self._attr_available = True
        else:
            self._attr_available = self._client.available
        await self._client.start()

    @callback
    def _handle_measurement_update(self, odb_id: int, value: ODBValue) -> None:
        """Track whether the heater has delivered a related state."""
        if odb_id != self.entity_description.availability_measurement_id:
            return
        self._has_seen_availability_state = True
        self._attr_available = True
        self.async_write_ha_state()

    async def async_press(self) -> None:
        """Execute the DHE button action."""
        try:
            method = getattr(self._client, self.entity_description.method)
            if self.entity_description.method_arg is None:
                await method()
            else:
                await method(self.entity_description.method_arg)
        except DHEError as err:
            _LOGGER.error("Could not execute DHE button %s: %s", self.entity_description.key, err)
            raise

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = available or self._has_seen_availability_state
        self.async_write_ha_state()
