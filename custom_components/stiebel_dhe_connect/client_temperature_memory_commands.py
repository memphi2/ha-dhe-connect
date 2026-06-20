"""Temperature-memory command helpers for the DHE client."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

from .client_command_context import command_context as _command_context
from .client_constants import APP_COMMAND_CONFIRMATION_TIMEOUT
from .client_types import DHEError, DHESession
from .client_value_helpers import (
    build_temperature_memory_button_value as _build_temperature_memory_button_value,
    clamp as _clamp,
    round_to_half_c as _round_to_half_c,
)
from .protocol import (
    DEFAULT_NEW_TEMPERATURE_MEMORY_C,
    DEFAULT_TEMPERATURE_MEMORY_NAMES,
    ID_SETPOINT_REQUEST,
    ODB_ASSIGN_COMMAND,
    TEMPERATURE_MEMORY_ID_TO_MEASUREMENT,
    TEMPERATURE_MEMORY_MAX_SLOTS,
    TEMPERATURE_MEMORY_SLOT_IDS,
    TEMPERATURE_MEMORY_SLOT_MEASUREMENTS,
    TEMP_MEMORY_ASSIGN_COMMAND,
    TEMP_MEMORY_GET_COMMAND,
)


class DHEClientTemperatureMemoryCommandsMixin:
    """Temperature-memory button, set, name and delete helpers."""

    async def press_temperature_memory(self, memory_slot: int) -> bool:
        try:
            memory_id = TEMPERATURE_MEMORY_SLOT_IDS[int(memory_slot)]
            measurement_id = TEMPERATURE_MEMORY_ID_TO_MEASUREMENT[memory_id]
        except KeyError as err:
            raise DHEError(f"Unsupported temperature memory slot: {memory_slot}") from err
        client = _command_context(self)

        async def _operation(ctx: DHESession) -> bool:
            temperature = await self._get_temperature_memory_temperature(
                ctx,
                memory_slot,
                measurement_id,
            )
            request_value = _build_temperature_memory_button_value(temperature)
            await client._post_packet(ctx, client._message_packet({
                "command": ODB_ASSIGN_COMMAND,
                "value": {"id": ID_SETPOINT_REQUEST, "value": request_value},
            }))
            with contextlib.suppress(DHEError):
                await client._request_setpoint(ctx)
            return True

        return await client._run_command_with_reconnect_retry(
            f"Could not press DHE temperature memory {memory_slot}",
            _operation,
        )

    async def _get_temperature_memory_temperature(
        self,
        ctx: DHESession,
        memory_slot: int,
        measurement_id: int,
    ) -> float:
        temperature = self._cached_temperature_memory_temperature(measurement_id)
        if temperature is not None:
            return temperature

        client = _command_context(self)
        await client._request_app_value(ctx, TEMP_MEMORY_GET_COMMAND)
        deadline = time.monotonic() + APP_COMMAND_CONFIRMATION_TIMEOUT
        while time.monotonic() < deadline:
            temperature = self._cached_temperature_memory_temperature(measurement_id)
            if temperature is not None:
                return temperature
            await asyncio.sleep(0.1)
        raise DHEError(f"DHE temperature memory {memory_slot} is not available yet")

    async def _refresh_temperature_memories(self, ctx: DHESession) -> None:
        client = _command_context(self)
        generation = client._temperature_memory_generation
        await client._request_app_value(ctx, TEMP_MEMORY_GET_COMMAND)
        deadline = time.monotonic() + APP_COMMAND_CONFIRMATION_TIMEOUT
        while time.monotonic() < deadline:
            if client._temperature_memory_generation != generation:
                return
            await asyncio.sleep(0.1)

    def _cached_temperature_memory_temperature(self, measurement_id: int) -> float | None:
        value = _command_context(self)._last_measurements.get(measurement_id)
        if value is None or isinstance(value, bool):
            return None
        return _round_to_half_c(_clamp(float(value), 20.0, 60.0))

    def _temperature_memory_ids(self, memory_slot: int) -> tuple[int, int]:
        try:
            slot = int(memory_slot)
            memory_id = TEMPERATURE_MEMORY_SLOT_IDS[slot]
            measurement_id = TEMPERATURE_MEMORY_SLOT_MEASUREMENTS[slot]
        except KeyError as err:
            raise DHEError(f"Unsupported temperature memory slot: {memory_slot}") from err
        return memory_id, measurement_id

    def _temperature_memory_exists(self, memory_id: int, measurement_id: int) -> bool:
        client = _command_context(self)
        return (
            memory_id in client._temperature_memory_ids_seen
            or measurement_id in client._last_measurements
        )

    def _can_create_temperature_memory(self, memory_id: int) -> bool:
        ids_seen = _command_context(self)._temperature_memory_ids_seen
        if len(ids_seen) >= TEMPERATURE_MEMORY_MAX_SLOTS:
            return False
        if not ids_seen:
            return memory_id == 0
        return memory_id == max(ids_seen) + 1

    def _temperature_memory_payload(
        self,
        memory_id: int,
        measurement_id: int,
        name: str,
        temperature: float,
    ) -> dict[str, Any]:
        exists = self._temperature_memory_exists(memory_id, measurement_id)
        if not exists and not self._can_create_temperature_memory(memory_id):
            raise DHEError("Temperature memories must be created in order")

        payload: dict[str, Any] = {
            "name": name,
            "temperature": temperature,
            "operation": "add_change",
        }
        if exists:
            payload["id"] = memory_id
        return payload

    async def set_temperature_memory(self, memory_slot: int, temperature: float) -> float:
        memory_id, measurement_id = self._temperature_memory_ids(memory_slot)

        requested = _round_to_half_c(_clamp(float(temperature), 20.0, 60.0))

        async def _operation(ctx: DHESession) -> float:
            await self._refresh_temperature_memories(ctx)
            client = _command_context(self)
            before_generation = client._temperature_memory_generation
            attributes = client._last_measurement_attributes.get(measurement_id, {})
            name = str(attributes.get("name", DEFAULT_TEMPERATURE_MEMORY_NAMES[memory_id]))
            payload = self._temperature_memory_payload(
                memory_id,
                measurement_id,
                name,
                requested,
            )
            await client._post_packet(ctx, client._message_packet({
                "command": TEMP_MEMORY_ASSIGN_COMMAND,
                "value": payload,
            }))
            await self._refresh_temperature_memories(ctx)
            if client._temperature_memory_generation == before_generation:
                raise DHEError(
                    f"DHE temperature memory {memory_slot} was not confirmed"
                )
            confirmed = self._cached_temperature_memory_temperature(measurement_id)
            if confirmed is None or abs(confirmed - requested) >= 0.01:
                raise DHEError(
                    f"DHE temperature memory {memory_slot} readback was {confirmed!r}, "
                    f"expected {requested!r}"
                )
            return confirmed

        return await _command_context(self)._run_command_with_reconnect_retry(
            f"Could not set DHE temperature memory {memory_slot}",
            _operation,
        )

    async def set_temperature_memory_name(self, memory_slot: int, name: str) -> str:
        memory_id, measurement_id = self._temperature_memory_ids(memory_slot)

        requested_name = str(name).strip()
        if not requested_name:
            raise DHEError(f"DHE temperature memory {memory_slot} name must not be empty")

        async def _operation(ctx: DHESession) -> str:
            await self._refresh_temperature_memories(ctx)
            client = _command_context(self)
            before_generation = client._temperature_memory_generation
            temperature = (
                self._cached_temperature_memory_temperature(measurement_id)
                or DEFAULT_NEW_TEMPERATURE_MEMORY_C
            )
            payload = self._temperature_memory_payload(
                memory_id,
                measurement_id,
                requested_name,
                temperature,
            )
            await client._post_packet(ctx, client._message_packet({
                "command": TEMP_MEMORY_ASSIGN_COMMAND,
                "value": payload,
            }))
            await self._refresh_temperature_memories(ctx)
            if client._temperature_memory_generation == before_generation:
                raise DHEError(
                    f"DHE temperature memory {memory_slot} name was not confirmed"
                )
            attributes = client._last_measurement_attributes.get(measurement_id, {})
            confirmed_name = str(attributes.get("name", "")).strip()
            if confirmed_name != requested_name:
                raise DHEError(
                    f"DHE temperature memory {memory_slot} name readback was "
                    f"{confirmed_name!r}, expected {requested_name!r}"
                )
            return confirmed_name

        return await _command_context(self)._run_command_with_reconnect_retry(
            f"Could not set DHE temperature memory {memory_slot} name",
            _operation,
        )

    async def delete_temperature_memory(self, memory_slot: int) -> bool:
        memory_id, measurement_id = self._temperature_memory_ids(memory_slot)

        async def _operation(ctx: DHESession) -> bool:
            await self._refresh_temperature_memories(ctx)
            if not self._temperature_memory_exists(memory_id, measurement_id):
                raise DHEError(f"DHE temperature memory {memory_slot} is not available")
            client = _command_context(self)
            await client._post_packet(ctx, client._message_packet({
                "command": TEMP_MEMORY_ASSIGN_COMMAND,
                "value": {
                    "id": memory_id,
                    "operation": "delete",
                },
            }))
            await self._refresh_temperature_memories(ctx)
            if self._temperature_memory_exists(memory_id, measurement_id):
                raise DHEError(f"DHE temperature memory {memory_slot} was not deleted")
            return True

        return await _command_context(self)._run_command_with_reconnect_retry(
            f"Could not delete DHE temperature memory {memory_slot}",
            _operation,
        )
