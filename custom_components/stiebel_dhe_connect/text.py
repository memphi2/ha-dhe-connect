"""Text platform for DHE Connect."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from homeassistant.components.text import TextEntity, TextEntityDescription, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .action_error_helpers import dhe_action_error
from .client import DHEClient
from .client_types import DHEError, MeasurementValue
from .entity_helpers import (
    StiebelDHEEntityMixin,
    temperature_memory_enabled_default,
    temperature_memory_icon,
    temperature_memory_measurement_slot_items,
)
from .entity_state_helpers import measurement_attribute_text, merge_state_attributes
from .protocol import (
    CONTROLUNIT_NAME_ASSIGN_COMMAND,
    CONTROLUNIT_NAME_MAX_LENGTH,
    CONTROLUNIT_NAME_SET_COMMAND,
    ID_DEVICE_INFO,
    TEMPERATURE_MEMORY_SLOT_MEASUREMENTS,
)
from .runtime_helpers import get_runtime_data

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class StiebelDHETextEntityDescription(TextEntityDescription):
    """Describe a writable DHE text setting."""

    measurement_id: int
    temperature_memory_slot: int


TEMPERATURE_MEMORY_MEASUREMENT_SLOT_ITEMS = temperature_memory_measurement_slot_items(
    TEMPERATURE_MEMORY_SLOT_MEASUREMENTS
)
CONTROLUNIT_NAME_TEXT_DESCRIPTION = TextEntityDescription(
    key="controlunit_name",
    translation_key="controlunit_name",
    icon="mdi:form-textbox",
)


def _temperature_memory_text_description(
    slot: int,
    measurement_id: int,
) -> StiebelDHETextEntityDescription:
    """Create the text description for a temperature memory slot."""
    return StiebelDHETextEntityDescription(
        key=f"temperature_memory_{slot}_name",
        translation_key=f"temperature_memory_{slot}_name",
        icon=temperature_memory_icon(slot),
        measurement_id=measurement_id,
        temperature_memory_slot=slot,
        entity_registry_enabled_default=temperature_memory_enabled_default(slot),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DHE text entities from a config entry."""
    runtime = get_runtime_data(hass, entry)
    client: DHEClient = runtime.client
    async_add_entities(
        [
            StiebelDHEControlUnitNameText(
                entry_id=entry.entry_id,
                name=runtime.name,
                client=client,
            )
        ]
        + [
            StiebelDHEText(
                entry_id=entry.entry_id,
                name=runtime.name,
                client=client,
                description=_temperature_memory_text_description(slot, measurement_id),
            )
            for measurement_id, slot in TEMPERATURE_MEMORY_MEASUREMENT_SLOT_ITEMS
        ]
    )


class StiebelDHEBaseText(StiebelDHEEntityMixin, TextEntity, RestoreEntity):
    """Shared write-deduping behavior for DHE text entities."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _last_written_text_signature: tuple[object, ...] | None

    def _measurement_attributes(self) -> dict[int, dict[str, object]]:
        """Return per-ODB attributes for this client with test compatibility."""
        if hasattr(self._client, "_last_measurement_attributes"):
            attributes = getattr(self._client, "_last_measurement_attributes")
        else:
            attributes = getattr(self._client, "last_measurement_attributes")
        if isinstance(attributes, dict):
            return cast(dict[int, dict[str, object]], attributes)
        return {}

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = available
        self._write_text_state()

    def _write_text_state(self, *, force: bool = False) -> bool:
        """Write text state only when visible state changed."""
        signature = self._text_write_signature()
        if not force and signature == getattr(
            self,
            "_last_written_text_signature",
            None,
        ):
            return False
        self._last_written_text_signature = signature
        self.async_write_ha_state()
        return True

    def _text_write_signature(self) -> tuple[object, ...]:
        """Return stable text fields that should trigger a state write."""
        return (
            self._attr_available,
            self._attr_native_value,
            dict(self._attr_extra_state_attributes or {}),
        )


class StiebelDHEText(StiebelDHEBaseText):
    """Writable DHE text setting represented as a Home Assistant text entity."""

    entity_description: StiebelDHETextEntityDescription
    _attr_entity_category = EntityCategory.CONFIG

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
        self._attr_available = False
        self._attr_native_value: str | None = None
        self._base_extra_state_attributes = {
            "temperature_memory_slot": self.entity_description.temperature_memory_slot,
            "memory_id": self.entity_description.temperature_memory_slot - 1,
            "source_command": "set:ste.common.temperature:memory",
        }
        self._last_written_text_signature: tuple[object, ...] | None = None
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
            self._attr_available = self._client.available
            self._update_extra_state_attributes()
            return

        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in {"unknown", "unavailable"}:
            self._attr_native_value = last_state.state
        self._attr_available = self._client.available
        self._update_extra_state_attributes()

    async def async_set_value(self, value: str) -> None:
        """Set the DHE temperature memory name."""
        try:
            confirmed = await self._client.set_temperature_memory_name(
                self.entity_description.temperature_memory_slot,
                value,
            )
        except DHEError as err:
            self._attr_available = self._client.available
            self._write_text_state(force=True)
            raise dhe_action_error(
                f"Could not set DHE text {self.entity_description.key}",
                err,
            ) from err

        self._attr_native_value = confirmed
        self._attr_available = True
        self._update_extra_state_attributes()
        self._write_text_state(force=True)

    @callback
    def _handle_measurement_update(self, odb_id: int, value: MeasurementValue) -> None:
        """Handle memory metadata updates from the persistent client."""
        if odb_id != self.entity_description.measurement_id:
            return

        if value is None or not self._set_value_from_client():
            self._attr_native_value = None
            self._attr_available = self._client.available
        else:
            self._attr_available = self._client.available
        self._update_extra_state_attributes()
        self._write_text_state()

    def _set_value_from_client(self) -> bool:
        attributes = self._measurement_attributes().get(
            self.entity_description.measurement_id,
            {},
        )
        name = measurement_attribute_text(attributes, "name")
        if name is None:
            return False
        self._attr_native_value = name
        return True

    def _update_extra_state_attributes(self) -> None:
        base_attributes = dict(self._base_extra_state_attributes)
        if self._attr_native_value is not None:
            base_attributes["name"] = self._attr_native_value
        self._attr_extra_state_attributes = merge_state_attributes(
            base_attributes,
            self._measurement_attributes().get(
                self.entity_description.measurement_id,
                {},
            ),
        )


class StiebelDHEControlUnitNameText(StiebelDHEBaseText):
    """Writable DHE device/control-unit name."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_min = 1
    _attr_native_max = CONTROLUNIT_NAME_MAX_LENGTH
    _attr_mode = TextMode.TEXT

    def __init__(self, entry_id: str, name: str, client: DHEClient) -> None:
        """Initialize the device-name text entity."""
        self.entity_description = CONTROLUNIT_NAME_TEXT_DESCRIPTION
        self._attr_translation_key = self.entity_description.translation_key
        self._attr_icon = self.entity_description.icon
        self._init_dhe_entity(
            entry_id=entry_id,
            key=str(self.entity_description.key),
            name=name,
            client=client,
        )
        self._attr_available = False
        self._attr_native_value: str | None = None
        self._base_extra_state_attributes = {
            "source_command": CONTROLUNIT_NAME_SET_COMMAND,
            "write_command": CONTROLUNIT_NAME_ASSIGN_COMMAND,
            "max_length": CONTROLUNIT_NAME_MAX_LENGTH,
        }
        self._last_written_text_signature: tuple[object, ...] | None = None
        self._update_extra_state_attributes()

    async def async_added_to_hass(self) -> None:
        """Subscribe to device-info and availability updates."""
        self.async_on_remove(
            self._client.add_measurement_callback(self._handle_measurement_update)
        )
        self.async_on_remove(
            self._client.add_availability_callback(self._handle_availability_update)
        )

        if self._set_value_from_client():
            self._attr_available = self._client.available
            self._update_extra_state_attributes()
            return

        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in {"unknown", "unavailable"}:
            self._attr_native_value = last_state.state
        self._attr_available = self._client.available
        self._update_extra_state_attributes()

    async def async_set_value(self, value: str) -> None:
        """Set the DHE device/control-unit name."""
        try:
            confirmed = await self._client.set_controlunit_name(value)
        except DHEError as err:
            self._attr_available = self._client.available
            self._write_text_state(force=True)
            raise dhe_action_error("Could not set DHE device name", err) from err

        self._attr_native_value = confirmed
        self._attr_available = True
        self._update_extra_state_attributes()
        self._write_text_state(force=True)

    @callback
    def _handle_measurement_update(self, odb_id: int, _value: MeasurementValue) -> None:
        """Handle DHE device-info updates."""
        if odb_id != ID_DEVICE_INFO:
            return
        if not self._set_value_from_client():
            self._attr_native_value = None
        self._attr_available = self._client.available
        self._update_extra_state_attributes()
        self._write_text_state()

    def _set_value_from_client(self) -> bool:
        name = self._client.last_device_info.get("controlunit_name")
        if name in (None, ""):
            attributes = self._measurement_attributes().get(ID_DEVICE_INFO, {})
            name = attributes.get("controlunit_name")
        text = str(name).strip() if name is not None else ""
        if not text:
            return False
        self._attr_native_value = text
        return True

    def _update_extra_state_attributes(self) -> None:
        attributes: dict[str, Any] = dict(self._base_extra_state_attributes)
        if self._attr_native_value is not None:
            attributes["name"] = self._attr_native_value
        self._attr_extra_state_attributes = attributes
