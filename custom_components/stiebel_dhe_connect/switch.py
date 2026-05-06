"""Switch platform for Stiebel DHE Connect."""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .client import DHEClient, DHEError, ID_ECO_MODE, ID_SHOWER_TIMER_ACTIVATION, ODBValue
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DHE switches from a config entry."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        StiebelDHEEcoModeSwitch(
            entry_id=entry.entry_id,
            name=runtime.name,
            client=runtime.client,
        ),
        StiebelDHEShowerTimerSwitch(
            entry_id=entry.entry_id,
            name=runtime.name,
            client=runtime.client,
        ),
    ])


class StiebelDHEEcoModeSwitch(SwitchEntity, RestoreEntity):
    """Eco mode switch backed by DHE ODB id 6."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False
    _attr_translation_key = "eco_mode"
    _attr_icon = "mdi:leaf"

    def __init__(self, entry_id: str, name: str, client: DHEClient) -> None:
        """Initialize the switch."""
        self._attr_unique_id = f"stiebel_dhe_connect_{entry_id}_eco_mode"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, client.host)},
            "manufacturer": "STIEBEL ELTRON",
            "model": "DHE Connect",
            "name": name,
        }
        self._attr_extra_state_attributes = {"odb_id": ID_ECO_MODE}
        self._client = client
        self._attr_available = False
        self._attr_is_on: bool | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to DHE updates and start the persistent session."""
        self.async_on_remove(
            self._client.add_measurement_callback(self._handle_measurement_update)
        )
        self.async_on_remove(
            self._client.add_availability_callback(self._handle_availability_update)
        )

        last_value = self._client.last_measurements.get(ID_ECO_MODE)
        if last_value is not None:
            self._attr_is_on = bool(last_value)
            self._attr_available = True
        else:
            last_state = await self.async_get_last_state()
            if last_state and last_state.state in {STATE_ON, STATE_OFF}:
                self._attr_is_on = last_state.state == STATE_ON
                self._attr_available = True

        await self._client.start()

    async def async_turn_on(self, **kwargs) -> None:  # noqa: ANN003
        """Turn Eco mode on."""
        try:
            self._attr_is_on = await self._client.set_eco_mode(True)
        except DHEError as err:
            self._attr_available = self._attr_is_on is not None
            self.async_write_ha_state()
            _LOGGER.error("Could not turn on DHE Eco mode: %s", err)
            raise
        self._attr_available = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:  # noqa: ANN003
        """Turn Eco mode off."""
        try:
            self._attr_is_on = await self._client.set_eco_mode(False)
        except DHEError as err:
            self._attr_available = self._attr_is_on is not None
            self.async_write_ha_state()
            _LOGGER.error("Could not turn off DHE Eco mode: %s", err)
            raise
        self._attr_available = True
        self.async_write_ha_state()

    @callback
    def _handle_measurement_update(self, odb_id: int, value: ODBValue) -> None:
        """Handle converted ODB value updates from the persistent client."""
        if odb_id != ID_ECO_MODE:
            return

        self._attr_is_on = bool(value)
        self._attr_available = True
        self.async_write_ha_state()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = available or self._attr_is_on is not None
        self.async_write_ha_state()


class StiebelDHEShowerTimerSwitch(StiebelDHEEcoModeSwitch):
    """Shower timer activation switch."""

    _attr_translation_key = "shower_timer_activation"
    _attr_icon = "mdi:timer-play"

    def __init__(self, entry_id: str, name: str, client: DHEClient) -> None:
        super().__init__(entry_id, name, client)
        self._attr_unique_id = f"stiebel_dhe_connect_{entry_id}_shower_timer_activation"
        self._attr_extra_state_attributes = {"command": "ste.app.showerTimer:activation"}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._client.add_measurement_callback(self._handle_measurement_update))
        self.async_on_remove(self._client.add_availability_callback(self._handle_availability_update))
        last_value = self._client.last_measurements.get(ID_SHOWER_TIMER_ACTIVATION)
        if last_value is not None:
            self._attr_is_on = bool(last_value)
            self._attr_available = True
        await self._client.start()

    async def async_turn_on(self, **kwargs) -> None:  # noqa: ANN003
        self._attr_is_on = await self._client.set_shower_timer_activation(True)
        self._attr_available = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:  # noqa: ANN003
        self._attr_is_on = await self._client.set_shower_timer_activation(False)
        self._attr_available = True
        self.async_write_ha_state()

    @callback
    def _handle_measurement_update(self, odb_id: int, value: ODBValue) -> None:
        if odb_id != ID_SHOWER_TIMER_ACTIVATION:
            return
        self._attr_is_on = bool(value)
        self._attr_available = True
        self.async_write_ha_state()
