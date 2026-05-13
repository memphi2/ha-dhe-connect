"""Switch platform for Stiebel DHE Connect."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .client import (
    BRUSH_TIMER_PATH,
    DHEClient,
    DHEError,
    ID_BATH_FILL_ACTIVE,
    ID_BRUSH_TIMER_ACTIVATION,
    ID_CHILD_SAFETY_ACTIVE,
    ID_ECO_MODE,
    ID_WELLNESS_ACTIVE,
    ID_WELLNESS_SHOWER_PROGRAM,
    ID_SHOWER_TIMER_ACTIVATION,
    ODBValue,
    SHOWER_TIMER_PATH,
)
from .entity_helpers import StiebelDHEEntityMixin
from .entity_state_helpers import (
    restored_switch_state,
    switch_state_from_value,
    value_available,
    wellness_program_switch_state,
)
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
        key="bath_fill_active",
        translation_key="bath_fill_active",
        icon="mdi:bathtub",
        measurement_id=ID_BATH_FILL_ACTIVE,
        turn_on_setter="start_bath_fill",
        turn_off_setter="stop_bath_fill",
    ),
    StiebelDHEODBSwitchDescription(
        key="child_safety_active",
        translation_key="child_safety_active",
        icon="mdi:thermometer-check",
        measurement_id=ID_CHILD_SAFETY_ACTIVE,
        turn_on_setter="set_child_safety_active",
        turn_on_args=(True,),
        turn_off_setter="set_child_safety_active",
        turn_off_args=(False,),
    ),
)


APP_TIMER_SWITCHES: tuple[StiebelDHEAppTimerSwitchDescription, ...] = (
    StiebelDHEAppTimerSwitchDescription(
        key="brush_timer_active",
        translation_key="brush_timer_active",
        icon="mdi:toothbrush",
        timer_path=BRUSH_TIMER_PATH,
        measurement_id=ID_BRUSH_TIMER_ACTIVATION,
        setter="set_brush_timer_activation",
    ),
    StiebelDHEAppTimerSwitchDescription(
        key="shower_timer_active",
        translation_key="shower_timer_active",
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
        key="wellness_winter_refresh",
        translation_key="wellness_winter_refresh",
        icon="mdi:snowflake-thermometer",
        program_id=2,
    ),
    StiebelDHEWellnessShowerProgramSwitchDescription(
        key="wellness_summer_fitness",
        translation_key="wellness_summer_fitness",
        icon="mdi:weather-sunny",
        program_id=3,
    ),
    StiebelDHEWellnessShowerProgramSwitchDescription(
        key="wellness_circulation_support",
        translation_key="wellness_circulation_support",
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


class StiebelDHEBaseSwitch(StiebelDHEEntityMixin, SwitchEntity, RestoreEntity):
    """Shared switch behavior for DHE-backed switches."""

    entity_description: SwitchEntityDescription
    _attr_has_entity_name = True
    _attr_should_poll = False

    def _init_switch_entity(
        self,
        *,
        entry_id: str,
        name: str,
        client: DHEClient,
        description: SwitchEntityDescription,
    ) -> None:
        """Initialize common switch identity and state."""
        self._attr_translation_key = description.translation_key
        self._attr_icon = description.icon
        self._attr_entity_category = description.entity_category
        self._init_dhe_entity(
            entry_id=entry_id,
            key=description.key,
            name=name,
            client=client,
        )
        self._attr_available = False
        self._attr_is_on: bool | None = None

    def _subscribe_to_switch_updates(self) -> None:
        """Subscribe to common switch update callbacks."""
        self.async_on_remove(
            self._client.add_measurement_callback(self._handle_measurement_update)
        )
        self.async_on_remove(
            self._client.add_availability_callback(self._handle_availability_update)
        )

    async def _restore_state_from_measurement(self, measurement_id: int) -> None:
        """Restore switch state from the latest client value or HA state."""
        last_value = self._client.last_measurements.get(measurement_id)
        if last_value is not None:
            self._set_switch_state_from_value(last_value)
            return

        await self._restore_last_switch_state()

    async def _restore_last_switch_state(self) -> bool:
        """Restore switch state from Home Assistant's last stored state."""
        last_state = await self.async_get_last_state()
        restored = restored_switch_state(last_state.state if last_state else None)
        if restored is None:
            return False

        self._attr_is_on = restored
        self._attr_available = True
        return True

    def _set_switch_state_from_value(self, value: ODBValue) -> None:
        """Update switch state from one client measurement value."""
        self._attr_is_on = switch_state_from_value(value)
        self._attr_available = self._attr_is_on is not None

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = value_available(available, self._attr_is_on)
        self.async_write_ha_state()


class StiebelDHEODBSwitch(StiebelDHEBaseSwitch):
    """Generic boolean switch backed by one ODB measurement id."""

    entity_description: StiebelDHEODBSwitchDescription

    def __init__(
        self,
        entry_id: str,
        name: str,
        client: DHEClient,
        description: StiebelDHEODBSwitchDescription,
    ) -> None:
        self.entity_description = description
        self._init_switch_entity(
            entry_id=entry_id,
            name=name,
            client=client,
            description=description,
        )
        self._attr_extra_state_attributes = {"odb_id": description.measurement_id}

    async def async_added_to_hass(self) -> None:
        """Subscribe to DHE updates and restore last known state."""
        self._subscribe_to_switch_updates()
        await self._restore_state_from_measurement(
            self.entity_description.measurement_id
        )

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
        self._set_switch_state_from_value(value)
        self.async_write_ha_state()


class StiebelDHEAppTimerSwitch(StiebelDHEBaseSwitch):
    """App timer activation switch."""

    entity_description: StiebelDHEAppTimerSwitchDescription

    def __init__(
        self,
        entry_id: str,
        name: str,
        client: DHEClient,
        description: StiebelDHEAppTimerSwitchDescription,
    ) -> None:
        self.entity_description = description
        self._init_switch_entity(
            entry_id=entry_id,
            name=name,
            client=client,
            description=description,
        )
        self._attr_extra_state_attributes = {
            "timer_path": description.timer_path,
            "timer_property": "activation",
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to DHE updates and restore last known state."""
        self._subscribe_to_switch_updates()
        await self._restore_state_from_measurement(
            self.entity_description.measurement_id
        )

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
            _LOGGER.error(
                "Could not set DHE app timer %s: %s",
                self.entity_description.key,
                err,
            )
            raise
        self._attr_available = True
        self.async_write_ha_state()

    @callback
    def _handle_measurement_update(self, odb_id: int, value: ODBValue) -> None:
        if odb_id != self.entity_description.measurement_id:
            return
        self._set_switch_state_from_value(value)
        self.async_write_ha_state()


class StiebelDHEWellnessShowerProgramSwitch(
    StiebelDHEBaseSwitch,
):
    """Wellness program switch based on ODB id 2."""

    entity_description: StiebelDHEWellnessShowerProgramSwitchDescription

    def __init__(
        self,
        entry_id: str,
        name: str,
        client: DHEClient,
        description: StiebelDHEWellnessShowerProgramSwitchDescription,
    ) -> None:
        self.entity_description = description
        self._init_switch_entity(
            entry_id=entry_id,
            name=name,
            client=client,
            description=description,
        )
        self._attr_extra_state_attributes = {
            "odb_id": ID_WELLNESS_SHOWER_PROGRAM,
            "program_value": description.program_id,
        }
        self._last_program_value: ODBValue | None = None
        self._program_active: bool | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to DHE updates and restore last known wellness state."""
        self._subscribe_to_switch_updates()

        last_active_value = self._client.last_measurements.get(ID_WELLNESS_ACTIVE)
        if last_active_value is not None:
            self._program_active = switch_state_from_value(last_active_value)

        last_program_value = self._client.last_measurements.get(
            ID_WELLNESS_SHOWER_PROGRAM
        )
        if last_program_value is not None:
            self._last_program_value = last_program_value
            self._attr_is_on = wellness_program_switch_state(
                self._last_program_value,
                self._program_active,
                self.entity_description.program_id,
            )
            self._attr_available = True
        else:
            await self._restore_last_switch_state()

    async def async_turn_on(self, **kwargs) -> None:  # noqa: ANN003
        try:
            await self._client.set_wellness_shower_program(
                self.entity_description.program_id
            )
            self._attr_is_on = True
        except DHEError as err:
            self._attr_available = self._attr_is_on is not None
            self.async_write_ha_state()
            _LOGGER.error(
                "Could not start DHE wellness program %s: %s",
                self.entity_description.key,
                err,
            )
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
            _LOGGER.error(
                "Could not stop DHE wellness program %s: %s",
                self.entity_description.key,
                err,
            )
            raise
        self._attr_available = True
        self.async_write_ha_state()

    @callback
    def _handle_measurement_update(self, odb_id: int, value: ODBValue) -> None:
        if odb_id == ID_WELLNESS_SHOWER_PROGRAM:
            self._last_program_value = value
        elif odb_id == ID_WELLNESS_ACTIVE:
            self._program_active = switch_state_from_value(value)
        else:
            return
        self._attr_is_on = wellness_program_switch_state(
            self._last_program_value,
            self._program_active,
            self.entity_description.program_id,
        )
        self._attr_available = True
        self.async_write_ha_state()
