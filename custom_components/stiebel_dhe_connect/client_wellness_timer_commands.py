"""Wellness and app-timer command helpers for the DHE client."""

from __future__ import annotations

from typing import Any

from .client_command_context import command_context as _command_context
from .client_constants import APP_COMMAND_CONFIRMATION_TIMEOUT
from .client_types import DHEError, DHESession, ODBValue
from .client_value_helpers import clamp as _clamp
from .client_value_helpers import raw_to_float as _raw_to_float
from .protocol import (
    BRUSH_TIMER_DEFAULT_DURATION_MINUTES,
    BRUSH_TIMER_PATH,
    ID_BRUSH_TIMER_ACTIVATION,
    ID_BRUSH_TIMER_DURATION,
    ID_BRUSH_TIMER_REMAINING,
    ID_SHOWER_TIMER_ACTIVATION,
    ID_SHOWER_TIMER_DURATION,
    ID_SHOWER_TIMER_REMAINING,
    ID_WELLNESS_ACTIVE,
    ID_WELLNESS_SHOWER_PROGRAM,
    SHOWER_TIMER_DEFAULT_DURATION_MINUTES,
    SHOWER_TIMER_PATH,
)


class DHEClientWellnessTimerCommandsMixin:
    """Wellness shower and app timer write helpers."""

    async def set_wellness_shower_program(self, program_id: int) -> bool:
        client = _command_context(self)
        await client.write_odb_value(ID_WELLNESS_SHOWER_PROGRAM, int(program_id))
        await client.write_odb_value(ID_WELLNESS_ACTIVE, True)
        return True

    async def stop_wellness_shower_program(self) -> bool:
        client = _command_context(self)
        await client.write_odb_value(ID_WELLNESS_ACTIVE, False)
        client._handle_measurement(ID_WELLNESS_ACTIVE, False, force_update=True)
        client._handle_measurement(ID_WELLNESS_SHOWER_PROGRAM, 0.0, force_update=True)
        return False

    async def set_brush_timer_duration_minutes(self, minutes: float) -> float:
        return await self._set_app_timer_duration_minutes(
            BRUSH_TIMER_PATH,
            ID_BRUSH_TIMER_DURATION,
            minutes,
        )

    async def set_brush_timer_activation(self, enabled: bool) -> bool:
        return await self._set_app_timer_activation(
            BRUSH_TIMER_PATH,
            ID_BRUSH_TIMER_ACTIVATION,
            enabled,
        )

    async def set_shower_timer_duration_minutes(self, minutes: float) -> float:
        return await self._set_app_timer_duration_minutes(
            SHOWER_TIMER_PATH,
            ID_SHOWER_TIMER_DURATION,
            minutes,
        )

    async def set_shower_timer_activation(self, enabled: bool) -> bool:
        return await self._set_app_timer_activation(
            SHOWER_TIMER_PATH,
            ID_SHOWER_TIMER_ACTIVATION,
            enabled,
        )

    async def reset_brush_timer(self) -> bool:
        return await self._reset_app_timer(
            BRUSH_TIMER_PATH,
            ID_BRUSH_TIMER_ACTIVATION,
            ID_BRUSH_TIMER_DURATION,
            ID_BRUSH_TIMER_REMAINING,
            BRUSH_TIMER_DEFAULT_DURATION_MINUTES,
        )

    async def reset_shower_timer(self) -> bool:
        return await self._reset_app_timer(
            SHOWER_TIMER_PATH,
            ID_SHOWER_TIMER_ACTIVATION,
            ID_SHOWER_TIMER_DURATION,
            ID_SHOWER_TIMER_REMAINING,
            SHOWER_TIMER_DEFAULT_DURATION_MINUTES,
        )

    async def _set_app_timer_duration_minutes(
        self,
        path: str,
        measurement_id: int,
        minutes: float,
    ) -> float:
        requested_minutes = _clamp(float(minutes), 1.0, 20.0)
        milliseconds = round(requested_minutes * 60000.0)
        confirmed = await self._write_app_value(
            f"assign:{path}:durationMilliseconds",
            milliseconds,
            measurement_id,
            float(requested_minutes),
        )
        return float(confirmed)

    async def _set_app_timer_activation(self, path: str, measurement_id: int, enabled: bool) -> bool:
        confirmed = await self._write_app_value(
            f"assign:{path}:activation",
            bool(enabled),
            measurement_id,
            bool(enabled),
        )
        return bool(confirmed)

    async def _reset_app_timer(
        self,
        path: str,
        activation_id: int,
        duration_id: int,
        remaining_id: int,
        default_duration: float,
    ) -> bool:
        client = _command_context(self)
        remaining = _configured_timer_duration_minutes(
            client,
            duration_id,
            default_duration,
        )
        await self._write_app_value(
            f"assign:{path}:reset",
            True,
            remaining_id,
            remaining,
        )
        client._handle_measurement(remaining_id, remaining, force_update=True)
        client._handle_measurement(activation_id, False, force_update=True)
        return True

    async def _write_app_value(self, command: str, value: Any, measurement_id: int, expected: ODBValue) -> ODBValue:
        client = _command_context(self)

        async def _operation(ctx: DHESession) -> ODBValue:
            future = client._new_write_future(measurement_id, expected)
            await client._post_packet(
                ctx,
                client._message_packet({"command": command, "value": value}),
            )
            try:
                return await client._wait_for_app_write_confirmation(future)
            except TimeoutError as err:
                client._clear_pending_write_future(None)
                raise DHEError(
                    f"No DHE app confirmation for {command} within "
                    f"{APP_COMMAND_CONFIRMATION_TIMEOUT:.1f}s"
                ) from err

        return await client._run_command_with_reconnect_retry(
            f"Could not write DHE app command {command}",
            _operation,
            on_error=lambda: client._clear_pending_write_future(None),
        )


def _configured_timer_duration_minutes(
    client: Any,
    duration_id: int,
    default_duration: float,
) -> float:
    """Return the last known configured app timer duration."""
    try:
        value = client._last_measurements.get(duration_id)
    except AttributeError:
        return default_duration
    try:
        return max(0.0, _raw_to_float(value))
    except (TypeError, ValueError):
        return default_duration
