"""Switch platform for Stiebel DHE Connect."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .client import (
    BRUSH_TIMER_PATH,
    DHEClient,
    DHEError,
    ID_BATH_FILL_ACTIVE,
    ID_BRUSH_TIMER_ACTIVATION,
    ID_ECO_MODE,
    ID_MAXIMUM_ACTIVE,
    ID_STOP_PROGRAM,
    ID_WELLNESS_SHOWER_PROGRAM,
    ID_SHOWER_TIMER_ACTIVATION,
    ODBValue,
    SHOWER_TIMER_PATH,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class StiebelDHEAppTimerSwitchDescription(SwitchEntityDescription):
    """Describe an app timer activation switch."""

    timer_path: str
    measurement_id: int
    setter: str


APP_TIMER_SWITCHES: tuple[StiebelDHEAppTimerSwitchDescription, ...] = (
    StiebelDHEAppTimerSwitchDescription(
        key="brush_timer_activation",
        translation_key="brush_timer_activation",
        icon="mdi:toothbrush",
        timer_path=BRUSH_TIMER_PATH,
        measurement_id=ID_BRUSH_TIMER_ACTIVATION,
        setter="set_brush_timer_activation",
    ),
    StiebelDHEAppTimerSwitchDescription(
        key="shower_timer_activation",
        translation_key="shower_timer_activation",
        icon="mdi:shower-head",
        timer_path=SHOWER_TIMER_PATH,
        measurement_id=ID_SHOWER_TIMER_ACTIVATION,
        setter="set_shower_timer_activation",
    ),
)


@dataclass(frozen=True, kw_only=True)
class StiebelDHEWellnessShowerProgramSwitchDescription(SwitchEntityDescription):
    """Describe a wellness program switch."""

    program_id: int


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
        StiebelDHEBathFillSwitch(
            entry_id=entry.entry_id,
            name=runtime.name,
            client=runtime.client,
        ),
        StiebelDHEMaximumActiveSwitch(
            entry_id=entry.entry_id,
            name=runtime.name,
            client=runtime.client,
        ),
        *[
            StiebelDHEWellnessShowerProgramSwitch(
                entry_id=entry.entry_id,
                name=runtime.name,
                client=runtime.client,
                description=description,
            )
            for description in (
                StiebelDHEWellnessShowerProgramSwitchDescription(
                    key="wellness_cold_prevention",
                    translation_key="wellness_cold_prevention",
                    icon="mdi:shower",
                    program_id=1,
                ),
                StiebelDHEWellnessShowerProgramSwitchDescription(
                    key="winter_refresh",
                    translation_key="winter_refresh",
                    icon="mdi:snowflake-thermometer",
                    program_id=2,
                ),
                StiebelDHEWellnessShowerProgramSwitchDescription(
                    key="summer_fitness",
                    translation_key="summer_fitness",
                    icon="mdi:weather-sunny",
                    program_id=3,
                ),
                StiebelDHEWellnessShowerProgramSwitchDescription(
                    key="circulation_support",
                    translation_key="circulation_support",
                    icon="mdi:heart-pulse",
                    program_id=4,
                ),
            )
        ],
        *[
            StiebelDHEAppTimerSwitch(
                entry_id=entry.entry_id,
                name=runtime.name,
                client=runtime.client,
                description=description,
            )
            for description in APP_TIMER_SWITCHES
        ],
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
            "identifiers": {(DOMAIN, f"{client.host}:{client.port}")},
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
        self.async_on_remove(self._client.add_measurement_callback(self._handle_measurement_update))
        self.async_on_remove(self._client.add_availability_callback(self._handle_availability_update))

        last_value = self._client.last_measurements.get(ID_ECO_MODE)
        if last_value is not None:
            self._attr_is_on = bool(last_value)
            self._attr_available = True
        else:
            last_state = await self.async_get_last_state()
            if last_state and last_state.state in {STATE_ON, STATE_OFF}:
                self._attr_is_on = last_state.state == STATE_ON
                self._attr_available = True

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
        self._attr_available = available and self._attr_is_on is not None
        self.async_write_ha_state()


class StiebelDHEBathFillSwitch(SwitchEntity, RestoreEntity):
    """Bath fill switch backed by DHE ODB id 1."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "bath_fill"
    _attr_icon = "mdi:bathtub"

    def __init__(self, entry_id: str, name: str, client: DHEClient) -> None:
        """Initialize the switch."""
        self._attr_unique_id = f"stiebel_dhe_connect_{entry_id}_bath_fill"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{client.host}:{client.port}")},
            "manufacturer": "STIEBEL ELTRON",
            "model": "DHE Connect",
            "name": name,
        }
        self._attr_extra_state_attributes = {"odb_id": ID_BATH_FILL_ACTIVE}
        self._client = client
        self._attr_available = False
        self._attr_is_on: bool | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to DHE updates and start the persistent session."""
        self.async_on_remove(self._client.add_measurement_callback(self._handle_measurement_update))
        self.async_on_remove(self._client.add_availability_callback(self._handle_availability_update))

        last_value = self._client.last_measurements.get(ID_BATH_FILL_ACTIVE)
        if last_value is not None:
            self._attr_is_on = bool(last_value)
            self._attr_available = True
        else:
            last_state = await self.async_get_last_state()
            if last_state and last_state.state in {STATE_ON, STATE_OFF}:
                self._attr_is_on = last_state.state == STATE_ON
                self._attr_available = True

    async def async_turn_on(self, **kwargs) -> None:  # noqa: ANN003
        """Start bath fill."""
        try:
            self._attr_is_on = await self._client.start_bath_fill()
        except DHEError as err:
            self._attr_available = self._attr_is_on is not None
            self.async_write_ha_state()
            _LOGGER.error("Could not start DHE bath fill: %s", err)
            raise
        self._attr_available = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:  # noqa: ANN003
        """Stop bath fill."""
        try:
            self._attr_is_on = await self._client.stop_bath_fill()
        except DHEError as err:
            self._attr_available = self._attr_is_on is not None
            self.async_write_ha_state()
            _LOGGER.error("Could not stop DHE bath fill: %s", err)
            raise
        self._attr_available = True
        self.async_write_ha_state()

    @callback
    def _handle_measurement_update(self, odb_id: int, value: ODBValue) -> None:
        """Handle converted ODB value updates from the persistent client."""
        if odb_id != ID_BATH_FILL_ACTIVE:
            return
        self._attr_is_on = bool(value)
        self._attr_available = True
        self.async_write_ha_state()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = available and self._attr_is_on is not None
        self.async_write_ha_state()


class StiebelDHEMaximumActiveSwitch(SwitchEntity, RestoreEntity):
    """Maximum temperature limit switch backed by DHE ODB id 4."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "maximum_active"
    _attr_icon = "mdi:thermometer-check"

    def __init__(self, entry_id: str, name: str, client: DHEClient) -> None:
        """Initialize the switch."""
        self._attr_unique_id = f"stiebel_dhe_connect_{entry_id}_maximum_active"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{client.host}:{client.port}")},
            "manufacturer": "STIEBEL ELTRON",
            "model": "DHE Connect",
            "name": name,
        }
        self._attr_extra_state_attributes = {"odb_id": ID_MAXIMUM_ACTIVE}
        self._client = client
        self._attr_available = False
        self._attr_is_on: bool | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to DHE updates and start the persistent session."""
        self.async_on_remove(self._client.add_measurement_callback(self._handle_measurement_update))
        self.async_on_remove(self._client.add_availability_callback(self._handle_availability_update))

        last_value = self._client.last_measurements.get(ID_MAXIMUM_ACTIVE)
        if last_value is not None:
            self._attr_is_on = bool(last_value)
            self._attr_available = True
        else:
            last_state = await self.async_get_last_state()
            if last_state and last_state.state in {STATE_ON, STATE_OFF}:
                self._attr_is_on = last_state.state == STATE_ON
                self._attr_available = True

    async def async_turn_on(self, **kwargs) -> None:  # noqa: ANN003
        """Enable the maximum temperature limit."""
        try:
            self._attr_is_on = await self._client.set_maximum_active(True)
        except DHEError as err:
            self._attr_available = self._attr_is_on is not None
            self.async_write_ha_state()
            _LOGGER.error("Could not enable DHE maximum temperature limit: %s", err)
            raise
        self._attr_available = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:  # noqa: ANN003
        """Disable the maximum temperature limit."""
        try:
            self._attr_is_on = await self._client.set_maximum_active(False)
        except DHEError as err:
            self._attr_available = self._attr_is_on is not None
            self.async_write_ha_state()
            _LOGGER.error("Could not disable DHE maximum temperature limit: %s", err)
            raise
        self._attr_available = True
        self.async_write_ha_state()

    @callback
    def _handle_measurement_update(self, odb_id: int, value: ODBValue) -> None:
        """Handle converted ODB value updates from the persistent client."""
        if odb_id != ID_MAXIMUM_ACTIVE:
            return
        self._attr_is_on = bool(value)
        self._attr_available = True
        self.async_write_ha_state()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = available and self._attr_is_on is not None
        self.async_write_ha_state()


class StiebelDHEAppTimerSwitch(SwitchEntity, RestoreEntity):
    """App timer activation switch."""

    entity_description: StiebelDHEAppTimerSwitchDescription
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry_id: str,
        name: str,
        client: DHEClient,
        description: StiebelDHEAppTimerSwitchDescription,
    ) -> None:
        self.entity_description = description
        self._attr_translation_key = description.translation_key
        self._attr_icon = description.icon
        self._attr_unique_id = f"stiebel_dhe_connect_{entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{client.host}:{client.port}")},
            "manufacturer": "STIEBEL ELTRON",
            "model": "DHE Connect",
            "name": name,
        }
        self._attr_extra_state_attributes = {
            "timer_path": description.timer_path,
            "timer_property": "activation",
        }
        self._client = client
        self._attr_available = False
        self._attr_is_on: bool | None = None

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._client.add_measurement_callback(self._handle_measurement_update))
        self.async_on_remove(self._client.add_availability_callback(self._handle_availability_update))
        last_value = self._client.last_measurements.get(self.entity_description.measurement_id)
        if last_value is not None:
            self._attr_is_on = bool(last_value)
            self._attr_available = True
        else:
            last_state = await self.async_get_last_state()
            if last_state and last_state.state in {STATE_ON, STATE_OFF}:
                self._attr_is_on = last_state.state == STATE_ON
                self._attr_available = True
    async def async_turn_on(self, **kwargs) -> None:  # noqa: ANN003
        await self._set_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:  # noqa: ANN003
        await self._set_enabled(False)

    async def _set_enabled(self, enabled: bool) -> None:
        try:
            setter = getattr(self._client, self.entity_description.setter)
            self._attr_is_on = await setter(enabled)
        except DHEError as err:
            self._attr_available = self._attr_is_on is not None
            self.async_write_ha_state()
            _LOGGER.error("Could not set DHE app timer %s: %s", self.entity_description.key, err)
            raise
        self._attr_available = True
        self.async_write_ha_state()

    @callback
    def _handle_measurement_update(self, odb_id: int, value: ODBValue) -> None:
        if odb_id != self.entity_description.measurement_id:
            return
        self._attr_is_on = bool(value)
        self._attr_available = True
        self.async_write_ha_state()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        self._attr_available = available and self._attr_is_on is not None
        self.async_write_ha_state()


class StiebelDHEWellnessShowerProgramSwitch(SwitchEntity, RestoreEntity):
    """Wellness program switch based on ODB id 2."""

    entity_description: StiebelDHEWellnessShowerProgramSwitchDescription
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry_id: str,
        name: str,
        client: DHEClient,
        description: StiebelDHEWellnessShowerProgramSwitchDescription,
    ) -> None:
        self.entity_description = description
        self._attr_translation_key = description.translation_key
        self._attr_icon = description.icon
        self._attr_unique_id = f"stiebel_dhe_connect_{entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{client.host}:{client.port}")},
            "manufacturer": "STIEBEL ELTRON",
            "model": "DHE Connect",
            "name": name,
        }
        self._attr_extra_state_attributes = {"odb_id": ID_WELLNESS_SHOWER_PROGRAM, "program_value": description.program_id}
        self._client = client
        self._attr_available = False
        self._attr_is_on: bool | None = None
        self._last_program_value: float | None = None
        self._program_active: bool | None = None

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._client.add_measurement_callback(self._handle_measurement_update))
        self.async_on_remove(self._client.add_availability_callback(self._handle_availability_update))
        last_value = self._client.last_measurements.get(ID_WELLNESS_SHOWER_PROGRAM)
        last_stop_value = self._client.last_measurements.get(ID_STOP_PROGRAM)
        if last_stop_value is not None:
            self._program_active = bool(last_stop_value)
        if last_value is not None:
            self._last_program_value = float(last_value)
            self._attr_is_on = self._program_active is not False and self._last_program_value == float(self.entity_description.program_id)
            self._attr_available = True
        else:
            last_state = await self.async_get_last_state()
            if last_state and last_state.state in {STATE_ON, STATE_OFF}:
                self._attr_is_on = last_state.state == STATE_ON
                self._attr_available = True

    async def async_turn_on(self, **kwargs) -> None:  # noqa: ANN003
        try:
            await self._client.set_wellness_shower_program(self.entity_description.program_id)
            self._attr_is_on = True
        except DHEError as err:
            self._attr_available = self._attr_is_on is not None
            self.async_write_ha_state()
            _LOGGER.error("Could not start DHE wellness program %s: %s", self.entity_description.key, err)
            raise
        self._attr_available = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:  # noqa: ANN003
        try:
            await self._client.stop_wellness_shower_program()
            self._attr_is_on = False
        except DHEError as err:
            self._attr_available = self._attr_is_on is not None
            self.async_write_ha_state()
            _LOGGER.error("Could not stop DHE wellness program %s: %s", self.entity_description.key, err)
            raise
        self._attr_available = True
        self.async_write_ha_state()

    @callback
    def _handle_measurement_update(self, odb_id: int, value: ODBValue) -> None:
        if odb_id == ID_WELLNESS_SHOWER_PROGRAM:
            self._last_program_value = float(value)
        elif odb_id == ID_STOP_PROGRAM:
            self._program_active = bool(value)
        else:
            return
        self._attr_is_on = (
            self._program_active is not False
            and self._last_program_value == float(self.entity_description.program_id)
        )
        self._attr_available = True
        self.async_write_ha_state()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        self._attr_available = available and self._attr_is_on is not None
        self.async_write_ha_state()
