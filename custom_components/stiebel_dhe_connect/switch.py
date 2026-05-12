"""Switch platform for Stiebel DHE Connect."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, callback
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
from .entity_helpers import StiebelDHEEntityMixin
from .entity_state_helpers import value_available
from .runtime_helpers import get_runtime_data

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class StiebelDHEAppTimerSwitchDescription(SwitchEntityDescription):
    """Describe an app timer activation switch."""

    timer_path: str
    measurement_id: int
    setter: str


@dataclass(frozen=True, kw_only=True)
class StiebelDHEODBSwitchDescription(SwitchEntityDescription):
    """Describe a boolean switch backed by one ODB measurement id."""

    measurement_id: int
    turn_on_setter: str
    turn_off_setter: str
    turn_on_args: tuple[object, ...] = ()
    turn_off_args: tuple[object, ...] = ()


ODB_SWITCHES: tuple[StiebelDHEODBSwitchDescription, ...] = (
    StiebelDHEODBSwitchDescription(
        key="eco_mode",
        translation_key="eco_mode",
        icon="mdi:leaf",
        measurement_id=ID_ECO_MODE,
        turn_on_setter="set_eco_mode",
        turn_on_args=(True,),
        turn_off_setter="set_eco_mode",
        turn_off_args=(False,),
    ),
    StiebelDHEODBSwitchDescription(
        key="bath_fill",
        translation_key="bath_fill",
        icon="mdi:bathtub",
        measurement_id=ID_BATH_FILL_ACTIVE,
        turn_on_setter="start_bath_fill",
        turn_off_setter="stop_bath_fill",
    ),
    StiebelDHEODBSwitchDescription(
        key="maximum_active",
        translation_key="maximum_active",
        icon="mdi:thermometer-check",
        measurement_id=ID_MAXIMUM_ACTIVE,
        turn_on_setter="set_maximum_active",
        turn_on_args=(True,),
        turn_off_setter="set_maximum_active",
        turn_off_args=(False,),
    ),
)


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


WELLNESS_PROGRAM_SWITCHES: tuple[StiebelDHEWellnessShowerProgramSwitchDescription, ...] = (
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DHE switches from a config entry."""
    runtime = get_runtime_data(hass, entry)
    async_add_entities([
        *[
            StiebelDHEODBSwitch(
                entry_id=entry.entry_id,
                name=runtime.name,
                client=runtime.client,
                description=description,
            )
            for description in ODB_SWITCHES
        ],
        *[
            StiebelDHEWellnessShowerProgramSwitch(
                entry_id=entry.entry_id,
                name=runtime.name,
                client=runtime.client,
                description=description,
            )
            for description in WELLNESS_PROGRAM_SWITCHES
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


class StiebelDHEODBSwitch(StiebelDHEEntityMixin, SwitchEntity, RestoreEntity):
    """Generic boolean switch backed by one ODB measurement id."""

    entity_description: StiebelDHEODBSwitchDescription
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry_id: str,
        name: str,
        client: DHEClient,
        description: StiebelDHEODBSwitchDescription,
    ) -> None:
        self.entity_description = description
        self._attr_translation_key = description.translation_key
        self._attr_icon = description.icon
        self._attr_entity_category = description.entity_category
        self._init_dhe_entity(
            entry_id=entry_id,
            key=description.key,
            name=name,
            client=client,
        )
        self._attr_extra_state_attributes = {"odb_id": description.measurement_id}
        self._attr_available = False
        self._attr_is_on: bool | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to DHE updates and restore last known state."""
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
        await self._set_enabled(
            self.entity_description.turn_on_setter,
            self.entity_description.turn_on_args,
            "turn on",
        )

    async def async_turn_off(self, **kwargs) -> None:  # noqa: ANN003
        await self._set_enabled(
            self.entity_description.turn_off_setter,
            self.entity_description.turn_off_args,
            "turn off",
        )

    async def _set_enabled(
        self,
        setter_name: str,
        setter_args: tuple[object, ...],
        action: str,
    ) -> None:
        try:
            setter = getattr(self._client, setter_name)
            self._attr_is_on = bool(await setter(*setter_args))
        except DHEError as err:
            self._attr_available = self._attr_is_on is not None
            self.async_write_ha_state()
            _LOGGER.error(
                "Could not %s DHE switch %s: %s",
                action,
                self.entity_description.key,
                err,
            )
            raise
        self._attr_available = True
        self.async_write_ha_state()

    @callback
    def _handle_measurement_update(self, odb_id: int, value: ODBValue) -> None:
        """Handle converted ODB value updates from the persistent client."""
        if odb_id != self.entity_description.measurement_id:
            return
        self._attr_is_on = bool(value)
        self._attr_available = True
        self.async_write_ha_state()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = value_available(available, self._attr_is_on)
        self.async_write_ha_state()


class StiebelDHEAppTimerSwitch(StiebelDHEEntityMixin, SwitchEntity, RestoreEntity):
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
        self._init_dhe_entity(
            entry_id=entry_id,
            key=description.key,
            name=name,
            client=client,
        )
        self._attr_extra_state_attributes = {
            "timer_path": description.timer_path,
            "timer_property": "activation",
        }
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
        self._attr_available = value_available(available, self._attr_is_on)
        self.async_write_ha_state()


class StiebelDHEWellnessShowerProgramSwitch(
    StiebelDHEEntityMixin,
    SwitchEntity,
    RestoreEntity,
):
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
        self._init_dhe_entity(
            entry_id=entry_id,
            key=description.key,
            name=name,
            client=client,
        )
        self._attr_extra_state_attributes = {"odb_id": ID_WELLNESS_SHOWER_PROGRAM, "program_value": description.program_id}
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
        self._attr_available = value_available(available, self._attr_is_on)
        self.async_write_ha_state()
