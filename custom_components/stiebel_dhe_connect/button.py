"""Button platform for Stiebel DHE Connect."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import DHEClient, DHEError, ID_BATH_FILL_ACTIVE
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class StiebelDHEButtonEntityDescription(ButtonEntityDescription):
    """Describe a DHE action button."""

    action: str
    icon: str


BUTTON_DESCRIPTIONS: tuple[StiebelDHEButtonEntityDescription, ...] = (
    StiebelDHEButtonEntityDescription(
        key="start_bath_fill",
        translation_key="start_bath_fill",
        action="start",
        icon="mdi:bathtub",
    ),
    StiebelDHEButtonEntityDescription(
        key="stop_bath_fill",
        translation_key="stop_bath_fill",
        action="stop",
        icon="mdi:stop-circle-outline",
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
        self._attr_extra_state_attributes = {"odb_id": ID_BATH_FILL_ACTIVE}
        self._client = client
        self._attr_available = False

    async def async_added_to_hass(self) -> None:
        """Subscribe to availability updates and start the persistent session."""
        self.async_on_remove(
            self._client.add_availability_callback(self._handle_availability_update)
        )
        self._attr_available = self._client.available
        await self._client.start()

    async def async_press(self) -> None:
        """Execute the DHE button action."""
        try:
            action: Callable[[], Awaitable[bool]]
            if self.entity_description.action == "start":
                action = self._client.start_bath_fill
            else:
                action = self._client.stop_bath_fill
            await action()
        except DHEError as err:
            _LOGGER.error("Could not execute DHE button %s: %s", self.entity_description.key, err)
            raise

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = available
        self.async_write_ha_state()
