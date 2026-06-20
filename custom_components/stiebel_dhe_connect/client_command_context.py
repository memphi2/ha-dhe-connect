"""Typing contracts shared by DHE client mixins."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol, TypeVar, cast

from .client_types import (
    AvailabilityCallback,
    DiagnosticCallback,
    DHESession,
    MeasurementCallback,
    MeasurementValue,
    ODBValue,
    OnlineCallback,
    ReconnectCallback,
    SetpointCallback,
)

if TYPE_CHECKING:
    import aiohttp
    from homeassistant.core import HomeAssistant

    from .client_connection_supervisor import DHEConnectionSupervisor

_T = TypeVar("_T")


class DHEClientConnectionContext(Protocol):
    """Connection-state surface required by the availability mixin."""

    _availability_callbacks: set[AvailabilityCallback]
    _available: bool
    _connection_supervisor: DHEConnectionSupervisor
    _ctx: DHESession | None
    _diagnostic_callbacks: set[DiagnosticCallback]
    _online: bool
    _online_callbacks: set[OnlineCallback]
    _ready: asyncio.Event
    _reconnect_grace_task: asyncio.Task[None] | None
    _stopped: asyncio.Event

    def _create_background_task(
        self,
        coro: Any,
        name: str,
    ) -> asyncio.Task[Any]:
        """Create a Home Assistant-owned background task."""

    def _notify_callbacks(
        self,
        callback_name: str,
        callbacks: set[Callable[..., None]],
        *args: Any,
    ) -> None:
        """Notify registered callbacks."""

    def _update_diagnostics(self, **updates: Any) -> None:
        """Update diagnostic runtime state."""

    def _copy_diagnostic_state(self) -> dict[str, Any]:
        """Return a copy of diagnostic runtime state."""


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
    _last_device_info: dict[str, Any]
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

    def _convert_odb_value(self, odb_id: int, raw_value: Any) -> ODBValue:
        """Convert a raw ODB value to Home Assistant-facing type."""

    def _co2_emission_to_raw(self, kg_per_kwh: float) -> int:
        """Convert CO2 emission value to the raw DHE representation."""


class DHEClientDiagnosticsContext(Protocol):
    """Public runtime state consumed by diagnostics exports."""

    @property
    def available(self) -> bool:
        """Return Home Assistant entity availability."""

    @property
    def online(self) -> bool:
        """Return whether the DHE runtime is currently online."""

    @property
    def reconnect_count(self) -> int:
        """Return successful reconnect count."""

    @property
    def diagnostic_state(self) -> dict[str, Any]:
        """Return sanitized runtime diagnostic state."""

    @property
    def reconnect_supervisor_state(self) -> dict[str, Any]:
        """Return reconnect-supervisor diagnostics."""

    @property
    def transport_statistics(self) -> dict[str, int]:
        """Return transport counters."""

    @property
    def runtime_parser_statistics(self) -> dict[str, Any]:
        """Return runtime parser counters."""

    @property
    def last_measurements(self) -> dict[int, MeasurementValue]:
        """Return cached measurements."""

    @property
    def last_measurement_attributes(self) -> dict[int, dict[str, Any]]:
        """Return cached measurement attributes."""

    @property
    def last_app_values(self) -> dict[str, Any]:
        """Return cached app values."""

    @property
    def last_device_info(self) -> dict[str, Any]:
        """Return cached device metadata."""

    @property
    def last_radio_state(self) -> dict[str, Any]:
        """Return cached radio state."""

    @property
    def last_weather_state(self) -> dict[str, Any]:
        """Return cached weather state."""


class DHEClientRuntimeContext(Protocol):
    """Runtime parser/readback surface required by runtime mixins."""

    _diagnostic_callbacks: set[DiagnosticCallback]
    _diagnostic_state: dict[str, Any]
    _last_app_values: dict[str, Any]
    _last_device_info: dict[str, Any]
    _last_measurement_attributes: dict[int, dict[str, Any]]
    _last_measurements: dict[int, MeasurementValue]
    _last_message_monotonic: float | None
    _last_power_fraction: float | None
    _last_runtime_parser_category: str | None
    _last_setpoint: float | None
    _measurement_callbacks: set[MeasurementCallback]
    _message_count: int
    _nominal_power_kw: float
    _pending_app_read_deadlines: dict[str, float]
    _pending_expected_setpoint: float | None
    _pending_odb_read_deadlines: dict[int, float]
    _pending_setpoint_future: asyncio.Future[float] | None
    _pending_write_expected: ODBValue | None
    _pending_write_future: asyncio.Future[ODBValue] | None
    _pending_write_id: int | None
    _runtime_parser_stats: dict[str, int]
    _setpoint_callbacks: set[SetpointCallback]

    async def _request_setpoint(self, ctx: DHESession) -> None:
        """Request setpoint readback."""

    async def _request_odb_value(self, ctx: DHESession, odb_id: int) -> None:
        """Request one ODB value."""

    def _publish_device_info_measurement(self) -> None:
        """Publish derived device-info measurement state."""

    def _notify_callbacks(
        self,
        callback_name: str,
        callbacks: set[Callable[..., None]],
        *args: Any,
    ) -> None:
        """Notify registered callbacks."""


class DHEClientTransportContext(Protocol):
    """Transport/authentication surface required by transport mixins."""

    base_url: str
    hass: HomeAssistant
    name: str
    port: int
    token_path: str
    _available: bool
    _ctx: DHESession | None
    _has_connected: bool
    _manual_pairing_requested: bool
    _pairing_active: bool
    _pairing_confirmed_success: bool
    _pairing_failed_explicit: bool
    _pairing_request_seen: bool
    _pairing_retry_attempts: int
    _pause_auto_reconnect_for_pairing: bool
    _ready: asyncio.Event
    _reconnect_callbacks: set[ReconnectCallback]
    _reconnect_count: int
    _reconnect_grace_task: asyncio.Task[None] | None
    _require_pairing_confirmation: bool
    _send_lock: asyncio.Lock
    _session: aiohttp.ClientSession
    _socketio_message_id: int
    _stopped: asyncio.Event
    _token: str | None
    _url_host: str
    _websocket_upgrade_failures: int

    def _record_pairing_progress(
        self,
        state: str,
        message: str,
        *,
        notify: bool = False,
        result: Any | None = None,
    ) -> None:
        """Record pairing progress."""

    def _record_pairing_requested(self) -> None:
        """Record that the DHE requested pairing confirmation."""

    def _record_pairing_result(self, result: Any) -> None:
        """Record one DHE pairing result."""

    def _record_pairing_failed(self, error: BaseException) -> None:
        """Record pairing failure."""

    def _set_online(self, online: bool) -> None:
        """Set online state."""

    def _set_available(
        self,
        available: bool,
        *,
        immediate: bool = False,
    ) -> None:
        """Set availability state."""

    def _mark_reconnecting(
        self,
        reason: str,
        *,
        immediate_availability: bool = False,
    ) -> float:
        """Mark runtime reconnecting and return next delay."""

    def _cancel_reconnect_grace_timer(self) -> None:
        """Cancel reconnect grace timer."""

    def _update_diagnostics(self, **updates: Any) -> None:
        """Update diagnostic runtime state."""

    def _notify_callbacks(
        self,
        callback_name: str,
        callbacks: set[Callable[..., None]],
        *args: Any,
    ) -> None:
        """Notify registered callbacks."""

    def _create_background_task(
        self,
        coro: Any,
        name: str,
    ) -> asyncio.Task[Any]:
        """Create a Home Assistant-owned background task."""


def connection_context(client: object) -> DHEClientConnectionContext:
    """Return the connection-state context for a mixin instance."""

    return cast(DHEClientConnectionContext, client)


def command_context(client: object) -> DHEClientCommandContext:
    """Return the command context for a mixin instance."""

    return cast(DHEClientCommandContext, client)


def diagnostics_context(client: object) -> DHEClientDiagnosticsContext:
    """Return the diagnostics context for a client-like object."""

    return cast(DHEClientDiagnosticsContext, client)


def runtime_context(client: object) -> DHEClientRuntimeContext:
    """Return the runtime context for a mixin instance."""

    return cast(DHEClientRuntimeContext, client)


def transport_context(client: object) -> DHEClientTransportContext:
    """Return the transport context for a mixin instance."""

    return cast(DHEClientTransportContext, client)
