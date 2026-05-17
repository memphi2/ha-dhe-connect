"""Typing contract shared by DHE client command mixins."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, TypeVar, cast

from .client_types import DHESession, MeasurementValue, ODBValue

_T = TypeVar("_T")


class DHEClientCommandContext(Protocol):
    """Runtime/transport surface required by command mixins."""

    _last_measurements: dict[int, MeasurementValue]
    _last_measurement_attributes: dict[int, dict[str, Any]]
    _last_radio_state: dict[str, Any]
    _last_radio_stations: list[dict[str, Any]]
    _last_radio_favorites: list[dict[str, Any]]
    _last_radio_catalogs: dict[str, list[str]]
    _radio_catalog_generations: dict[str, int]
    _radio_stations_generation: int
    _radio_favorites_generation: int
    _weather_search_generation: int
    _weather_favorites_generation: int
    _weather_countries_generation: int
    _last_weather_countries: list[dict[str, Any]]
    _temperature_memory_ids_seen: set[int]
    _temperature_memory_generation: int

    async def _run_command_with_reconnect_retry(
        self,
        error_message: str,
        operation: Callable[[DHESession], Awaitable[_T]],
        *,
        timeout: float = 45.0,
        on_error: Callable[[], None] | None = None,
    ) -> _T:
        """Run a command with the client's reconnect retry policy."""

    async def _run_command_without_reconnect_retry(
        self,
        error_message: str,
        operation: Callable[[DHESession], Awaitable[_T]],
        *,
        timeout: float = 45.0,
    ) -> _T:
        """Run a command without reconnect retry."""

    async def write_odb_value(self, odb_id: int, value: Any) -> ODBValue:
        """Write an ODB value through the core command mixin."""

    async def _post_packet(self, ctx: DHESession, packet: str) -> str:
        """Post a Socket.IO packet."""

    def _message_packet(self, payload: dict[str, Any]) -> str:
        """Build a Socket.IO message packet."""

    async def _request_setpoint(self, ctx: DHESession) -> None:
        """Request current setpoint readback."""

    async def _request_app_value(self, ctx: DHESession, command: str) -> None:
        """Request an app value from the DHE."""

    async def _send_ste_command(
        self,
        ctx: DHESession,
        command: str,
        value: Any,
    ) -> None:
        """Send an STE command."""

    def _new_setpoint_future(
        self,
        expected: float | None = None,
    ) -> asyncio.Future[float]:
        """Create a pending setpoint confirmation future."""

    def _clear_pending_future(self, err: Exception | None) -> None:
        """Clear a pending setpoint confirmation future."""

    def _new_write_future(
        self,
        odb_id: int,
        expected: ODBValue | None = None,
    ) -> asyncio.Future[ODBValue]:
        """Create a pending write confirmation future."""

    def _clear_pending_write_future(self, err: Exception | None) -> None:
        """Clear a pending write confirmation future."""

    async def _wait_for_setpoint_confirmation(
        self,
        ctx: DHESession,
        future: asyncio.Future[float],
    ) -> float:
        """Wait for a setpoint readback confirmation."""

    async def _wait_for_write_confirmation(
        self,
        ctx: DHESession,
        future: asyncio.Future[ODBValue],
        odb_id: int,
    ) -> ODBValue:
        """Wait for an ODB write readback confirmation."""

    async def _wait_for_app_write_confirmation(
        self,
        future: asyncio.Future[ODBValue],
    ) -> ODBValue:
        """Wait for an app write confirmation."""

    async def _wait_for_radio_stations(
        self,
        previous_generation: int,
    ) -> list[dict[str, Any]]:
        """Wait for radio station results."""

    async def _wait_for_radio_favorites(
        self,
        previous_generation: int,
    ) -> list[dict[str, Any]]:
        """Wait for radio favorites."""

    async def _wait_for_radio_catalog(
        self,
        attribute: str,
        previous_generation: int,
    ) -> list[str]:
        """Wait for a radio catalog."""

    async def _wait_for_radio_station(self, station_id: int) -> None:
        """Wait until a radio station is selected."""

    def _radio_favorites(self) -> list[dict[str, Any]]:
        """Return current radio favorites."""

    def _handle_radio_value(self, command: str, raw_value: Any) -> None:
        """Handle a radio state value."""

    async def _wait_for_weather_search_results(
        self,
        previous_generation: int,
    ) -> list[dict[str, Any]]:
        """Wait for weather search results."""

    async def _wait_for_weather_countries(
        self,
        previous_generation: int,
    ) -> list[dict[str, Any]]:
        """Wait for weather countries."""

    async def _wait_for_weather_favorites(
        self,
        previous_generation: int,
    ) -> list[dict[str, Any]]:
        """Wait for weather favorites."""

    async def _wait_for_weather_location(self, location_id: str) -> None:
        """Wait until a weather location is selected."""

    def _weather_favorites(self) -> list[dict[str, Any]]:
        """Return current weather favorites."""

    def _handle_measurement(
        self,
        odb_id: int,
        value: MeasurementValue,
        *,
        force_update: bool = False,
    ) -> None:
        """Handle a measurement value."""

    def _handle_currency_value(self, raw_value: Any, *, source_command: str) -> None:
        """Handle the selected currency value."""

    def _convert_odb_value(self, odb_id: int, raw_value: Any) -> ODBValue:
        """Convert a raw ODB value to Home Assistant-facing type."""

    def _co2_emission_to_raw(self, kg_per_kwh: float) -> int:
        """Convert CO2 emission value to the raw DHE representation."""


def command_context(client: object) -> DHEClientCommandContext:
    """Return the command context for a mixin instance."""

    return cast(DHEClientCommandContext, client)
