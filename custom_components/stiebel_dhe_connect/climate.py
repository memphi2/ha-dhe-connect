"""Climate platform for Stiebel DHE Connect."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import ClimateEntityFeature, HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import DHEClient, DHEError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the climate entity from a config entry."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        StiebelDHEClimate(
            entry_id=entry.entry_id,
            name=runtime.name,
            client=runtime.client,
            poll_interval=runtime.poll_interval,
        )
    ])


class StiebelDHEClimate(ClimateEntity):
    """Stiebel DHE setpoint entity with persistent local polling session."""

    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_hvac_mode = HVACMode.HEAT
    _attr_min_temp = 20.0
    _attr_max_temp = 60.0
    _attr_target_temperature_step = 0.5
    _attr_should_poll = False

    def __init__(self, entry_id: str, name: str, client: DHEClient, poll_interval: int) -> None:
        """Initialize the entity."""
        self._attr_name = name
        self._attr_unique_id = f"stiebel_dhe_connect_{entry_id}_setpoint"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, client.host)},
            "manufacturer": "STIEBEL ELTRON",
            "model": "DHE Connect",
            "name": name,
        }
        self._client = client
        self._poll_interval = max(60, int(poll_interval))
        self._attr_target_temperature: float | None = None
        self._attr_available = False
        self._attr_extra_state_attributes = {
            "communication_model": "persistent_socketio_polling",
            "readback_id": 0,
            "write_id": 66,
            "poll_interval_seconds": self._poll_interval,
        }

    async def async_added_to_hass(self) -> None:
        """Start persistent DHE connection and value polling."""
        await self._client.start(
            poll_interval=self._poll_interval,
            setpoint_callback=self._handle_setpoint_update,
            availability_callback=self._handle_availability_update,
        )
        self.async_on_remove(lambda: self.hass.async_create_task(self._client.stop()))

    @callback
    def _handle_setpoint_update(self, value: float) -> None:
        """Handle setpoint updates from the persistent client."""
        self._attr_target_temperature = value
        self._attr_available = True
        self.async_write_ha_state()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = available
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature and update state from write readback."""
        if ATTR_TEMPERATURE not in kwargs:
            return

        temperature = float(kwargs[ATTR_TEMPERATURE])

        try:
            self._attr_target_temperature = await self._client.set_temperature(temperature)
            self._attr_available = True
            self.async_write_ha_state()
        except DHEError as err:
            _LOGGER.error("Could not set DHE temperature: %s", err)
            raise
