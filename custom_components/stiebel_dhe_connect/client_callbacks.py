"""Callback registration and task helpers for the DHE client."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .client_types import (
    AvailabilityCallback,
    CallbackRemover,
    DiagnosticCallback,
    MeasurementCallback,
    MeasurementValue,
    OnlineCallback,
    RadioCallback,
    ReconnectCallback,
    SetpointCallback,
    WeatherCallback,
    WellnessProgramsCallback,
)
from .async_helpers import create_background_task
from .protocol import TEMPERATURE_MEMORY_SLOT_MEASUREMENTS

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class DHEClientCallbacksMixin:
    """Register DHE callbacks and fan out state updates."""

    if TYPE_CHECKING:
        hass: HomeAssistant
        _available: bool
        _availability_callbacks: set[AvailabilityCallback]
        _diagnostic_callbacks: set[DiagnosticCallback]
        _last_measurements: dict[int, MeasurementValue]
        _last_wellness_programs: tuple[dict[str, Any], ...]
        _last_setpoint: float | None
        _measurement_callbacks: set[MeasurementCallback]
        _online: bool
        _online_callbacks: set[OnlineCallback]
        _radio_callbacks: set[RadioCallback]
        _reconnect_callbacks: set[ReconnectCallback]
        _reconnect_count: int
        _setpoint_callbacks: set[SetpointCallback]
        _temperature_memory_full_list_seen: bool
        _weather_callbacks: set[WeatherCallback]
        _wellness_program_callbacks: set[WellnessProgramsCallback]

        def _copy_diagnostic_state(self) -> dict[str, Any]: ...

        def _copy_radio_state(self) -> dict[str, Any]: ...

        def _copy_weather_state(self) -> dict[str, Any]: ...

    def add_setpoint_callback(self, callback: SetpointCallback) -> CallbackRemover:
        remove = self._add_callback(self._setpoint_callbacks, callback)
        if self._last_setpoint is not None:
            self._call_callback("setpoint", callback, self._last_setpoint)
        return remove

    def add_availability_callback(
        self,
        callback: AvailabilityCallback,
    ) -> CallbackRemover:
        remove = self._add_callback(self._availability_callbacks, callback)
        self._call_callback("availability", callback, self._available)
        return remove

    def add_online_callback(self, callback: OnlineCallback) -> CallbackRemover:
        remove = self._add_callback(self._online_callbacks, callback)
        self._call_callback("online", callback, self._online)
        return remove

    def add_measurement_callback(
        self,
        callback: MeasurementCallback,
        *,
        replay: bool = True,
    ) -> CallbackRemover:
        remove = self._add_callback(self._measurement_callbacks, callback)
        if not replay:
            return remove
        for odb_id, value in self._last_measurements.items():
            self._call_callback("measurement", callback, odb_id, value)
        if self._temperature_memory_full_list_seen:
            for measurement_id in TEMPERATURE_MEMORY_SLOT_MEASUREMENTS.values():
                if measurement_id in self._last_measurements:
                    continue
                self._call_callback("measurement", callback, measurement_id, None)
        return remove

    def add_reconnect_callback(self, callback: ReconnectCallback) -> CallbackRemover:
        remove = self._add_callback(self._reconnect_callbacks, callback)
        self._call_callback("reconnect", callback, self._reconnect_count)
        return remove

    def add_radio_callback(self, callback: RadioCallback) -> CallbackRemover:
        remove = self._add_callback(self._radio_callbacks, callback)
        self._call_callback("radio", callback, self._copy_radio_state())
        return remove

    def add_weather_callback(self, callback: WeatherCallback) -> CallbackRemover:
        remove = self._add_callback(self._weather_callbacks, callback)
        self._call_callback("weather", callback, self._copy_weather_state())
        return remove

    def add_wellness_programs_callback(
        self,
        callback: WellnessProgramsCallback,
    ) -> CallbackRemover:
        remove = self._add_callback(self._wellness_program_callbacks, callback)
        self._call_callback(
            "wellness_programs",
            callback,
            tuple(dict(program) for program in self._last_wellness_programs),
        )
        return remove

    def add_diagnostic_callback(self, callback: DiagnosticCallback) -> CallbackRemover:
        remove = self._add_callback(self._diagnostic_callbacks, callback)
        self._call_callback("diagnostic", callback, self._copy_diagnostic_state())
        return remove

    @staticmethod
    def _add_callback(
        callbacks: set[Callable[..., None]],
        callback: Callable[..., None],
    ) -> CallbackRemover:
        callbacks.add(callback)

        def _remove_callback() -> None:
            callbacks.discard(callback)

        return _remove_callback

    def _notify_callbacks(
        self,
        callback_name: str,
        callbacks: set[Callable[..., None]],
        *args: Any,
    ) -> None:
        if not callbacks:
            return
        for callback in tuple(callbacks):
            self._call_callback(callback_name, callback, *args)

    @staticmethod
    def _call_callback(
        callback_name: str,
        callback: Callable[..., None],
        *args: Any,
    ) -> None:
        try:
            callback(*args)
        except Exception:  # noqa: BLE001
            DHEClientCallbacksMixin._log_callback_exception(callback_name)

    @staticmethod
    def _log_callback_exception(callback_name: str) -> None:
        _LOGGER.debug("DHE %s callback raised an exception", callback_name, exc_info=True)

    def _create_background_task(self, coro: Any, name: str) -> asyncio.Task[Any]:
        return create_background_task(self.hass, coro, name)
