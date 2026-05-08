"""Select platform for Stiebel DHE Connect."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .client import DHEClient, DHEError, ID_APP_CURRENCY, MeasurementValue
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CURRENCY_OPTIONS = (
    "EUR",
    "GBP",
    "CZK",
    "PLN",
    "CNY",
    "USD",
    "AUD",
    "HKD",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DHE select entities from a config entry."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        StiebelDHECurrencySelect(
            entry_id=entry.entry_id,
            name=runtime.name,
            client=runtime.client,
        )
    ])


class StiebelDHECurrencySelect(SelectEntity, RestoreEntity):
    """Currency select backed by the DHE app currency setting."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_icon = "mdi:currency-eur"
    _attr_should_poll = False
    _attr_translation_key = "currency"

    def __init__(self, entry_id: str, name: str, client: DHEClient) -> None:
        """Initialize the currency select."""
        self._attr_unique_id = f"stiebel_dhe_connect_{entry_id}_currency"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, client.host)},
            "manufacturer": "STIEBEL ELTRON",
            "model": "DHE Connect",
            "name": name,
        }
        self._attr_extra_state_attributes = {
            "source_command": "get:ste.common.currency:value",
        }
        self._client = client
        self._currency_options = list(CURRENCY_OPTIONS)
        self._attr_options = list(self._currency_options)
        self._attr_available = False
        self._attr_current_option: str | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to DHE measurement and availability updates."""
        self.async_on_remove(
            self._client.add_measurement_callback(self._handle_measurement_update)
        )
        self.async_on_remove(
            self._client.add_availability_callback(self._handle_availability_update)
        )

        last_value = self._client.last_measurements.get(ID_APP_CURRENCY)
        if last_value is not None:
            self._set_current_option(last_value)
            self._attr_available = True
            return

        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in {"unknown", "unavailable"}:
            self._set_current_option(last_state.state)
            self._attr_available = True

    async def async_select_option(self, option: str) -> None:
        """Set the DHE currency."""
        try:
            confirmed = await self._client.set_currency(option)
        except DHEError as err:
            self._attr_available = self._attr_current_option is not None
            self.async_write_ha_state()
            _LOGGER.error("Could not set DHE currency: %s", err)
            raise

        self._set_current_option(confirmed)
        self._attr_available = True
        self.async_write_ha_state()

    @callback
    def _handle_measurement_update(self, odb_id: int, value: MeasurementValue) -> None:
        """Handle converted currency updates from the persistent client."""
        if odb_id != ID_APP_CURRENCY:
            return
        self._set_current_option(value)
        self._attr_available = True
        self.async_write_ha_state()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = available or self._attr_current_option is not None
        self.async_write_ha_state()

    def _set_current_option(self, value: MeasurementValue) -> None:
        option = str(value).strip().upper()
        if not option or option == "UNSET":
            return
        if option not in self._currency_options:
            self._currency_options.append(option)
            self._attr_options = list(self._currency_options)
        self._attr_current_option = option
