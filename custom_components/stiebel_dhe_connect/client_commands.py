"""Core write helpers for the DHE client."""

from __future__ import annotations

from typing import Any

from .client_command_context import command_context as _command_context
from .client_device_info_commands import DHEClientDeviceInfoCommandsMixin
from .client_radio_commands import DHEClientRadioCommandsMixin
from .client_temperature_memory_commands import DHEClientTemperatureMemoryCommandsMixin
from .client_weather_commands import DHEClientWeatherCommandsMixin
from .client_wellness_timer_commands import DHEClientWellnessTimerCommandsMixin
from .client_types import DHEError, DHESession, MeasurementValue, ODBValue
from .client_value_helpers import (
    build_req66 as _build_req66,
    c_to_raw_tenths as _c_to_raw_tenths,
    clamp as _clamp,
    round_to_half_c as _round_to_half_c,
    values_equal as _values_equal,
    water_heating_enabled_to_raw as _water_heating_enabled_to_raw,
)
from .protocol import (
    CO2_EMISSION_MAX,
    ELECTRICITY_PRICE_MAX,
    ID_BATH_FILL_ACTIVE,
    ID_BATH_FILL_TARGET_VOLUME,
    ID_CHILD_SAFETY_ACTIVE,
    ID_CHILD_SAFETY_TEMPERATURE_LIMIT,
    ID_CO2_EMISSION_RAW,
    ID_ECO_FLOW_LIMIT,
    ID_ECO_MODE,
    ID_ELECTRICITY_PRICE_CENTS,
    ID_ELECTRICITY_PRICE_EUROS,
    ID_SETPOINT_REQUEST,
    ID_WATER_HEATING_ENABLED,
    ID_WATER_PRICE_CENTS,
    ID_WATER_PRICE_EUROS,
    ODB_ASSIGN_COMMAND,
    TEMPERATURE_MAX_OVERRIDE_ASSIGN_COMMAND,
    SET_REQ_OFF_VALUE,
    WATER_PRICE_MAX,
)


class DHEClientCommandsMixin(
    DHEClientDeviceInfoCommandsMixin,
    DHEClientRadioCommandsMixin,
    DHEClientWeatherCommandsMixin,
    DHEClientTemperatureMemoryCommandsMixin,
    DHEClientWellnessTimerCommandsMixin,
):
    """User-facing core write commands."""

    def _next_setpoint_request_address(self) -> int:
        current = getattr(self, "_setpoint_request_address", 0)
        next_address = (current % 63) + 1
        self._setpoint_request_address = next_address
        return next_address

    async def set_temperature(self, temperature: float) -> float:
        requested = _round_to_half_c(_clamp(float(temperature), 20.0, 60.0))
        client = _command_context(self)

        async def _operation(ctx: DHESession) -> float:
            addr = self._next_setpoint_request_address()
            req_value = _build_req66(requested, addr)
            future = client._new_setpoint_future(requested)
            await client._post_packet(ctx, client._message_packet({
                "command": ODB_ASSIGN_COMMAND,
                "value": {"id": ID_SETPOINT_REQUEST, "value": req_value},
            }))
            readback = await client._wait_for_setpoint_confirmation(ctx, future)
            if abs(readback - requested) < 0.01:
                return readback
            raise DHEError(f"readback was {readback:.1f} C, expected {requested:.1f} C")

        return await client._run_command_with_reconnect_retry(
            "Could not set DHE setpoint",
            _operation,
            on_error=lambda: client._clear_pending_future(None),
        )

    async def set_heating_off(self) -> None:
        """Backward-compatible wrapper for the known DHE sync request."""
        await self._send_set_req_sync()

    async def set_water_heating_enabled(self, enabled: bool) -> bool:
        """Enable or disable water heating via ODB id 33 and sync request."""
        requested = bool(enabled)
        client = _command_context(self)
        confirmed = bool(
            await client.write_odb_value(
                ID_WATER_HEATING_ENABLED,
                _water_heating_enabled_to_raw(requested),
            )
        )
        await self._send_set_req_sync()
        return confirmed

    async def _send_set_req_sync(self) -> None:
        """Send the observed ID 66 sync request used by the native app."""
        client = _command_context(self)

        async def _operation(ctx: DHESession) -> None:
            await client._post_packet(
                ctx,
                client._message_packet(
                    {
                        "command": ODB_ASSIGN_COMMAND,
                        "value": {
                            "id": ID_SETPOINT_REQUEST,
                            "value": SET_REQ_OFF_VALUE,
                        },
                    }
                ),
            )

        await client._run_command_with_reconnect_retry(
            "Could not send DHE set-req sync",
            _operation,
        )

    async def write_odb_value(self, odb_id: int, value: Any) -> ODBValue:
        client = _command_context(self)
        expected = client._convert_odb_value(odb_id, value)

        async def _operation(ctx: DHESession) -> ODBValue:
            future = client._new_write_future(odb_id, expected)
            await client._post_packet(ctx, client._message_packet({
                "command": ODB_ASSIGN_COMMAND,
                "value": {"id": int(odb_id), "value": value},
            }))
            confirmed = await client._wait_for_write_confirmation(ctx, future, odb_id)
            if _values_equal(confirmed, expected):
                return confirmed
            raise DHEError(f"write confirmation was {confirmed!r}, expected {expected!r}")

        return await client._run_command_with_reconnect_retry(
            f"Could not write DHE ODB id {odb_id}",
            _operation,
            on_error=lambda: client._clear_pending_write_future(None),
        )

    async def start_bath_fill(self) -> bool:
        return bool(await self.write_odb_value(ID_BATH_FILL_ACTIVE, True))

    async def stop_bath_fill(self) -> bool:
        return bool(await self.write_odb_value(ID_BATH_FILL_ACTIVE, False))

    async def set_bath_fill_target_volume(self, liters: float) -> float:
        requested = round(_clamp(float(liters), 5.0, 200.0))
        return float(await self.write_odb_value(ID_BATH_FILL_TARGET_VOLUME, requested))

    async def set_child_safety_temperature_limit(self, temperature: float) -> float:
        requested = _round_to_half_c(_clamp(float(temperature), 20.0, 60.0))
        return float(
            await self.write_odb_value(
                ID_CHILD_SAFETY_TEMPERATURE_LIMIT,
                _c_to_raw_tenths(requested),
            )
        )

    async def set_child_safety_active(self, enabled: bool) -> bool:
        return bool(await self.write_odb_value(ID_CHILD_SAFETY_ACTIVE, bool(enabled)))

    async def bridge_temperature_maximum(self) -> bool:
        """Temporarily bridge the DHE maximum temperature for 5 minutes."""
        client = _command_context(self)

        async def _operation(ctx: DHESession) -> bool:
            await client._send_ste_command(
                ctx,
                TEMPERATURE_MAX_OVERRIDE_ASSIGN_COMMAND,
                True,
            )
            return True

        return await client._run_command_with_reconnect_retry(
            "Could not bridge DHE maximum temperature",
            _operation,
        )

    async def set_eco_mode(self, enabled: bool) -> bool:
        return bool(await self.write_odb_value(ID_ECO_MODE, bool(enabled)))

    async def set_eco_flow_limit(self, liters_per_minute: float) -> float:
        requested_l_min = _round_to_half_c(_clamp(float(liters_per_minute), 4.0, 15.0))
        raw_value = round(requested_l_min * 10.0)
        return float(await self.write_odb_value(ID_ECO_FLOW_LIMIT, raw_value))

    async def set_electricity_price(self, euros_per_kwh: float) -> float:
        return await self._set_price(
            euros_per_kwh,
            ID_ELECTRICITY_PRICE_EUROS,
            ID_ELECTRICITY_PRICE_CENTS,
            max_value=ELECTRICITY_PRICE_MAX,
        )

    async def set_water_price(self, euros_per_m3: float) -> float:
        return await self._set_price(
            euros_per_m3,
            ID_WATER_PRICE_EUROS,
            ID_WATER_PRICE_CENTS,
            max_value=WATER_PRICE_MAX,
        )

    async def set_co2_emission(self, kg_per_kwh: float) -> float:
        client = _command_context(self)
        value = round(_clamp(float(kg_per_kwh), 0.0, CO2_EMISSION_MAX), 3)
        raw_value = client._co2_emission_to_raw(value)
        await client.write_odb_value(ID_CO2_EMISSION_RAW, raw_value)
        return value

    async def _set_price(
        self,
        value: float,
        euros_odb_id: int,
        cents_odb_id: int,
        *,
        max_value: float,
    ) -> float:
        client = _command_context(self)
        old_euros = client._last_measurements.get(euros_odb_id)
        old_cents = client._last_measurements.get(cents_odb_id)
        total_cents = round(_clamp(float(value), 0.0, max_value) * 100)
        euros, cents = divmod(total_cents, 100)
        attempted_components: list[tuple[int, MeasurementValue]] = []
        try:
            attempted_components.append((euros_odb_id, old_euros))
            await client.write_odb_value(euros_odb_id, euros)
            attempted_components.append((cents_odb_id, old_cents))
            await client.write_odb_value(cents_odb_id, cents)
        except (DHEError, RuntimeError) as err:
            rollback_errors = await self._rollback_price_components(attempted_components)
            if rollback_errors:
                raise DHEError(
                    f"{err}; price rollback failed: {'; '.join(rollback_errors)}"
                ) from err
            raise
        return total_cents / 100.0

    async def _rollback_price_components(
        self,
        components: list[tuple[int, MeasurementValue]],
    ) -> list[str]:
        """Best-effort restore of price components after a partial write."""
        client = _command_context(self)
        errors: list[str] = []
        for odb_id, old_value in reversed(components):
            if old_value is None:
                continue
            try:
                await client.write_odb_value(odb_id, old_value)
            except (DHEError, RuntimeError) as err:
                errors.append(f"ODB id {odb_id}: {err}")
        return errors
