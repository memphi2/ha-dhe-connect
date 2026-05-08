"""Binary sensor platform for Stiebel DHE Connect."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import DHEClient
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DHE binary sensors from a config entry."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            StiebelDHEOnlineBinarySensor(
                entry_id=entry.entry_id,
                name=runtime.name,
                client=runtime.client,
            )
        ]
    )


class StiebelDHEOnlineBinarySensor(BinarySensorEntity):
    """DHE online status diagnostic binary sensor."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "online"

    def __init__(self, entry_id: str, name: str, client: DHEClient) -> None:
        """Initialize the online status binary sensor."""
        self._attr_unique_id = f"stiebel_dhe_connect_{entry_id}_online"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, client.host)},
            "manufacturer": "STIEBEL ELTRON",
            "model": "DHE Connect",
            "name": name,
        }
        self._client = client
        self._attr_available = True
        self._attr_is_on = client.online

    async def async_added_to_hass(self) -> None:
        """Subscribe to DHE online updates and start the persistent session."""
        self.async_on_remove(
            self._client.add_online_callback(self._handle_online_update)
        )
        self._attr_is_on = self._client.online

    @callback
    def _handle_online_update(self, online: bool) -> None:
        """Handle DHE online status updates."""
        self._attr_is_on = online
        self.async_write_ha_state()
