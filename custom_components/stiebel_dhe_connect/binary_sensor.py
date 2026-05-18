"""Binary sensor platform for Stiebel DHE Connect."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import DHEClient
from .client_types import MeasurementValue
from .entity_helpers import StiebelDHEEntityMixin
from .entity_state_helpers import coerce_float, merge_state_attributes, value_available
from .protocol import ID_SCALD_PROTECTION_ACTIVE
from .runtime_helpers import get_runtime_data


@dataclass(frozen=True, kw_only=True)
class StiebelDHEBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describe a DHE binary sensor."""

    odb_id: int | None = None
    radio_key: str | None = None
    extra_state_attributes: dict[str, Any] | None = None


BINARY_SENSOR_DESCRIPTIONS: tuple[StiebelDHEBinarySensorEntityDescription, ...] = (
    StiebelDHEBinarySensorEntityDescription(
        key="scald_protection_active",
        translation_key="scald_protection_active",
        icon="mdi:shield-check",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        odb_id=ID_SCALD_PROTECTION_ACTIVE,
    ),
    StiebelDHEBinarySensorEntityDescription(
        key="bluetooth_paired",
        translation_key="bluetooth_paired",
        icon="mdi:bluetooth-connect",
        entity_category=EntityCategory.DIAGNOSTIC,
        radio_key="paired",
        extra_state_attributes={
            "radio_path": "ste.app.radio",
            "radio_property": "paired",
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DHE binary sensors from a config entry."""
    runtime = get_runtime_data(hass, entry)
    async_add_entities(
        [
            StiebelDHEBinarySensor(
                entry_id=entry.entry_id,
                name=runtime.name,
                client=runtime.client,
                description=description,
            )
            for description in BINARY_SENSOR_DESCRIPTIONS
        ]
    )


class StiebelDHEBinarySensor(StiebelDHEEntityMixin, BinarySensorEntity):
    """Converted DHE binary sensor."""

    entity_description: StiebelDHEBinarySensorEntityDescription
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry_id: str,
        name: str,
        client: DHEClient,
        description: StiebelDHEBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        self.entity_description = description
        self._attr_translation_key = description.translation_key
        self._attr_device_class = description.device_class
        self._attr_entity_category = description.entity_category
        self._attr_entity_registry_enabled_default = (
            description.entity_registry_enabled_default
        )
        self._attr_icon = description.icon
        self._init_dhe_entity(
            entry_id=entry_id,
            key=description.key,
            name=name,
            client=client,
        )
        base_extra_state_attributes = dict(description.extra_state_attributes or {})
        if description.odb_id is not None:
            base_extra_state_attributes["odb_id"] = description.odb_id
        self._base_extra_state_attributes = base_extra_state_attributes
        self._attr_extra_state_attributes = dict(self._base_extra_state_attributes)
        self._attr_available = False
        self._attr_is_on: bool | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to DHE state updates."""
        if self.entity_description.odb_id is not None:
            self.async_on_remove(
                self._client.add_measurement_callback(self._handle_measurement_update)
            )
        if self.entity_description.radio_key is not None:
            self.async_on_remove(
                self._client.add_radio_callback(self._handle_radio_update)
            )
        self.async_on_remove(
            self._client.add_availability_callback(self._handle_availability_update)
        )

        if self.entity_description.odb_id is not None:
            last_value = self._client.last_measurements.get(self.entity_description.odb_id)
            if last_value is not None:
                self._update_state(last_value)
        if self.entity_description.radio_key is not None:
            self._update_radio_state(self._client.last_radio_state)

    def _convert_value(self, value: MeasurementValue) -> bool | None:
        if isinstance(value, bool):
            return value
        numeric_value = coerce_float(value)
        if numeric_value is None:
            return None
        return bool(int(numeric_value))

    def _update_extra_state_attributes(self) -> None:
        dynamic_attributes = {}
        if self.entity_description.odb_id is not None:
            dynamic_attributes = self._client.last_measurement_attributes.get(
                self.entity_description.odb_id,
                {},
            )
        self._attr_extra_state_attributes = merge_state_attributes(
            self._base_extra_state_attributes,
            dynamic_attributes,
        )

    def _update_state(self, value: MeasurementValue) -> None:
        self._update_extra_state_attributes()
        self._attr_is_on = self._convert_value(value)
        self._attr_available = value_available(self._client.available, self._attr_is_on)

    def _update_radio_state(self, state: dict[str, Any]) -> None:
        radio_key = self.entity_description.radio_key
        if radio_key is None or radio_key not in state:
            return
        self._update_state(state.get(radio_key))

    @callback
    def _handle_measurement_update(self, odb_id: int, value: MeasurementValue) -> None:
        """Handle converted measurement updates from the persistent client."""
        if odb_id != self.entity_description.odb_id:
            return
        self._update_state(value)
        self.async_write_ha_state()

    @callback
    def _handle_radio_update(self, state: dict[str, Any]) -> None:
        """Handle radio state updates from the persistent client."""
        previous = self._attr_is_on
        self._update_radio_state(state)
        if self._attr_is_on != previous:
            self.async_write_ha_state()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = value_available(available, self._attr_is_on)
        self.async_write_ha_state()
