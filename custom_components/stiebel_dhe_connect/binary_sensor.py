"""Binary sensor platform for DHE Connect."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import DHEClient
from .client_types import MeasurementValue
from .entity_helpers import StiebelDHEEntityMixin
from .entity_state_helpers import coerce_float, merge_state_attributes, value_available
from .protocol import ID_SCALD_PROTECTION_ACTIVE
from .runtime_helpers import get_runtime_data

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class StiebelDHEBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describe a DHE binary sensor."""

    odb_id: int


BINARY_SENSOR_DESCRIPTIONS: tuple[StiebelDHEBinarySensorEntityDescription, ...] = (
    StiebelDHEBinarySensorEntityDescription(
        key="scald_protection_active",
        translation_key="scald_protection_active",
        icon="mdi:shield-check",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        odb_id=ID_SCALD_PROTECTION_ACTIVE,
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
        self._base_extra_state_attributes = {"odb_id": description.odb_id}
        self._attr_extra_state_attributes = dict(self._base_extra_state_attributes)
        self._attr_available = False
        self._attr_is_on: bool | None = None
        self._last_written_binary_signature: tuple[Any, ...] | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to DHE measurements."""
        self.async_on_remove(
            self._client.add_measurement_callback(
                self._handle_measurement_update,
                replay=False,
            )
        )
        self.async_on_remove(
            self._client.add_availability_callback(self._handle_availability_update)
        )

        last_value = self._client.last_measurements.get(self.entity_description.odb_id)
        if last_value is not None:
            self._update_state(last_value)

    def _convert_value(self, value: MeasurementValue) -> bool | None:
        if isinstance(value, bool):
            return value
        numeric_value = coerce_float(value)
        if numeric_value is None:
            return None
        return bool(int(numeric_value))

    def _update_extra_state_attributes(self) -> None:
        self._attr_extra_state_attributes = merge_state_attributes(
            self._base_extra_state_attributes,
            self._client._last_measurement_attributes.get(
                self.entity_description.odb_id,
                {},
            ),
        )

    def _update_state(self, value: MeasurementValue) -> None:
        self._update_extra_state_attributes()
        self._attr_is_on = self._convert_value(value)
        self._attr_available = value_available(self._client.available, self._attr_is_on)

    @callback
    def _handle_measurement_update(self, odb_id: int, value: MeasurementValue) -> None:
        """Handle converted measurement updates from the persistent client."""
        if odb_id != self.entity_description.odb_id:
            return
        self._update_state(value)
        self._write_binary_state()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = value_available(available, self._attr_is_on)
        self._write_binary_state()

    def _write_binary_state(self, *, force: bool = False) -> bool:
        """Write binary sensor state only when visible state changed."""
        signature = self._binary_write_signature()
        if not force and signature == self._last_written_binary_signature:
            return False
        self._last_written_binary_signature = signature
        self.async_write_ha_state()
        return True

    def _binary_write_signature(self) -> tuple[Any, ...]:
        """Return stable binary sensor fields that should trigger a state write."""
        return (
            self._attr_available,
            self._attr_is_on,
            dict(self._attr_extra_state_attributes or {}),
        )
