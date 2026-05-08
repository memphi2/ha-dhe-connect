"""Text platform for Stiebel DHE Connect."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.text import TextEntity, TextEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .client import (
    DHEClient,
    DHEError,
    MeasurementValue,
    TEMPERATURE_MEMORY_SLOT_MEASUREMENTS,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class StiebelDHETextEntityDescription(TextEntityDescription):
    """Describe a writable DHE text setting."""

    measurement_id: int
    temperature_memory_slot: int


TEXT_DESCRIPTIONS: tuple[StiebelDHETextEntityDescription, ...] = (
    *(
        StiebelDHETextEntityDescription(
            key=f"temperature_memory_{slot}_name",
            translation_key=f"temperature_memory_{slot}_name",
            icon=f"mdi:numeric-{slot}-box-outline" if slot < 10 else "mdi:counter",
            measurement_id=measurement_id,
            temperature_memory_slot=slot,
        )
        for slot, measurement_id in TEMPERATURE_MEMORY_SLOT_MEASUREMENTS.items()
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DHE text entities from a config entry."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            StiebelDHEText(
                entry_id=entry.entry_id,
                name=runtime.name,
                client=runtime.client,
                description=description,
            )
            for description in TEXT_DESCRIPTIONS
        ]
    )


class StiebelDHEText(TextEntity, RestoreEntity):
    """Writable DHE text setting represented as a Home Assistant text entity."""

    entity_description: StiebelDHETextEntityDescription
    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry_id: str,
        name: str,
        client: DHEClient,
        description: StiebelDHETextEntityDescription,
    ) -> None:
        """Initialize the text entity."""
        self.entity_description = description
        self._attr_translation_key = description.translation_key
        self._attr_unique_id = f"stiebel_dhe_connect_{entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, client.host)},
            "manufacturer": "STIEBEL ELTRON",
            "model": "DHE Connect",
            "name": name,
        }
        self._client = client
        self._attr_available = False
        self._attr_native_value: str | None = None
        self._update_extra_state_attributes()

    async def async_added_to_hass(self) -> None:
        """Subscribe to DHE measurements and availability updates."""
        self.async_on_remove(
            self._client.add_measurement_callback(self._handle_measurement_update)
        )
        self.async_on_remove(
            self._client.add_availability_callback(self._handle_availability_update)
        )

        if self._set_value_from_client():
            self._attr_available = True
            self._update_extra_state_attributes()
            return

        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in {"unknown", "unavailable"}:
            self._attr_native_value = last_state.state
            self._attr_available = True

    async def async_set_value(self, value: str) -> None:
        """Set the DHE temperature memory name."""
        try:
            confirmed = await self._client.set_temperature_memory_name(
                self.entity_description.temperature_memory_slot,
                value,
            )
        except DHEError as err:
            self._attr_available = self._attr_native_value is not None
            self.async_write_ha_state()
            _LOGGER.error("Could not set DHE text %s: %s", self.entity_description.key, err)
            raise

        self._attr_native_value = confirmed
        self._attr_available = True
        self._update_extra_state_attributes()
        self.async_write_ha_state()

    @callback
    def _handle_measurement_update(self, odb_id: int, value: MeasurementValue) -> None:
        """Handle memory metadata updates from the persistent client."""
        if odb_id != self.entity_description.measurement_id:
            return

        self._set_value_from_client()
        self._attr_available = True
        self._update_extra_state_attributes()
        self.async_write_ha_state()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = available or self._attr_native_value is not None
        self.async_write_ha_state()

    def _set_value_from_client(self) -> bool:
        attributes = self._client.last_measurement_attributes.get(
            self.entity_description.measurement_id,
            {},
        )
        name = attributes.get("name")
        if name in (None, ""):
            return False
        self._attr_native_value = str(name)
        return True

    def _update_extra_state_attributes(self) -> None:
        attributes = {
            "temperature_memory_slot": self.entity_description.temperature_memory_slot,
        }
        attributes.update(
            self._client.last_measurement_attributes.get(
                self.entity_description.measurement_id,
                {},
            )
        )
        self._attr_extra_state_attributes = attributes
