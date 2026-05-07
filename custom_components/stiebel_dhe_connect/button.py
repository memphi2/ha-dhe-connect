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
    availability_measurement_id: int
    timer_path: str
    timer_property: str


BUTTON_DESCRIPTIONS: tuple[StiebelDHEButtonEntityDescription, ...] = (
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
    StiebelDHEButtonEntityDescription(
        key="wellness_shower_program_winter_refresh",
        translation_key="wellness_shower_program_winter_refresh",
        method="run_wellness_shower_program_winter_refresh",
        icon="mdi:snowflake-thermometer",
        availability_measurement_id=ID_SHOWER_TIMER_ACTIVATION,
        timer_path="ste.common.odb",
        timer_property="id:2 + id:10",
    ),
    StiebelDHEButtonEntityDescription(
        key="wellness_shower_program_summer_fitness",
        translation_key="wellness_shower_program_summer_fitness",
        method="run_wellness_shower_program_summer_fitness",
        icon="mdi:weather-sunny",
        availability_measurement_id=ID_SHOWER_TIMER_ACTIVATION,
        timer_path="ste.common.odb",
        timer_property="id:2 + id:10",
    ),
    StiebelDHEButtonEntityDescription(
        key="wellness_shower_program_circulation_support",
        translation_key="wellness_shower_program_circulation_support",
        method="run_wellness_shower_program_circulation_support",
        icon="mdi:heart-pulse",
        availability_measurement_id=ID_SHOWER_TIMER_ACTIVATION,
        timer_path="ste.common.odb",
        timer_property="id:2 + id:10",
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
        self._attr_extra_state_attributes = {
            "timer_path": description.timer_path,
            "timer_property": description.timer_property,
        }
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
        if self._client.last_measurements.get(self.entity_description.availability_measurement_id) is not None:
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
            await method()
        except DHEError as err:
            _LOGGER.error("Could not execute DHE button %s: %s", self.entity_description.key, err)
            raise

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = available or self._has_seen_availability_state
        self.async_write_ha_state()
