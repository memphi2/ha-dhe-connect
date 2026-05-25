"""Persistent local Socket.IO/Engine.IO v3 client for DHE Connect."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import aiohttp

from .async_helpers import cancel_task_if_pending
from .client_command_runner import DHEClientCommandRunnerMixin
from .client_commands import DHEClientCommandsMixin
from .client_callbacks import DHEClientCallbacksMixin
from .client_connection_state import DHEClientConnectionStateMixin
from .client_constants import DEFAULT_NOMINAL_POWER_KW
from .client_constants import RUNTIME_STARTUP_PROOF_TIMEOUT_SECONDS
from .client_diagnostics import diagnostic_error as _diagnostic_error
from .client_errors import (
    DHE_TRANSPORT_EXCEPTIONS as _DHE_TRANSPORT_EXCEPTIONS,
    runtime_transport_error_or_raise as _runtime_transport_error_or_raise,
    suppress_transport_errors as _suppress_transport_errors,
)
from .client_pairing import DHEClientPairingMixin
from .client_connection_supervisor import DHEConnectionSupervisor
from .client_runtime import DHEClientRuntimeMixin
from .client_transport import DHEClientTransportMixin
from .client_web_version import DHEClientWebVersionMixin
from .client_types import (
    AvailabilityCallback,
    DHEAuthError,
    DHEError,
    DHESession,
    DiagnosticCallback,
    MeasurementCallback,
    MeasurementValue,
    ODBValue,
    OnlineCallback,
    RadioCallback,
    ReconnectCallback,
    SetpointCallback,
    WeatherCallback,
    WellnessProgramsCallback,
)

if TYPE_CHECKING:
    from .client_command_context import (
        DHEClientCommandContext,
        DHEClientConnectionContext,
        DHEClientDiagnosticsContext,
        DHEClientRuntimeContext,
        DHEClientTransportContext,
    )
from .connection_helpers import (
    host_for_url as _host_for_url,
    normalize_host as _normalize_host,
    validate_port as _validate_port,
)
from .protocol import (
    APP_TIMER_REQUEST_COMMANDS,
    CONSUMPTION_REQUEST_COMMANDS,
    DEVICE_INFO_REQUEST_COMMANDS,
    ID_BATH_FILL_CURRENT_VOLUME,
    ID_BATH_FILL_TARGET_VOLUME,
    ID_CHILD_SAFETY_ACTIVE,
    ID_CO2_EMISSION_RAW,
    ID_DEVICE_STATUS,
    ID_NOMINAL_POWER,
    ID_POWER_PERCENT,
    ID_PROTOCOL_VERSION,
    ID_SCALD_PROTECTION_ACTIVE,
    ID_SETPOINT,
    ID_WATER_FLOW,
    ID_WATER_HEATING_ENABLED,
    INITIAL_VALUE_IDS,
    ODB_GET_COMMAND,
    OPTIONAL_STARTUP_APP_REQUEST_COMMANDS,
    OPTIONAL_STARTUP_ODB_IDS,
    RADIO_CATALOG_FIELDS,
    RADIO_PATH,
)

_LOGGER = logging.getLogger(__name__)
DEVICE_INFO_REQUEST_TIMEOUT_SECONDS = 5.0
RUNTIME_STARTUP_PROOF_IDS = frozenset(INITIAL_VALUE_IDS) - {ID_PROTOCOL_VERSION}


class DHEClient(
    DHEClientPairingMixin,
    DHEClientCallbacksMixin,
    DHEClientConnectionStateMixin,
    DHEClientCommandsMixin,
    DHEClientCommandRunnerMixin,
    DHEClientWebVersionMixin,
    DHEClientRuntimeMixin,
    DHEClientTransportMixin,
):
    """Persistent Engine.IO v3 WebSocket client for DHE Connect."""

    def __init__(
        self, hass: HomeAssistant, host: str, port: int, token_file: str, name: str
    ) -> None:
        self.hass = hass
        self.host = _normalize_host(host)
        self._url_host = _host_for_url(self.host)
        self.port = _validate_port(port)
        self.name = name
        self.device_identifier: str | None = None
        self.base_url = f"http://{self._url_host}:{self.port}"
        self.token_path = (
            token_file if os.path.isabs(token_file) else hass.config.path(token_file)
        )
        self._owns_session = False
        try:
            self._session = async_get_clientsession(hass)
        except RuntimeError as err:
            # In early setup-test flows the HA frame helper may not yet be ready;
            # keep setup robust by using a scoped local session.
            _LOGGER.debug("Falling back to direct aiohttp.ClientSession: %s", err)
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        self._ctx: DHESession | None = None
        self._token: str | None = None
        self._runner: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        self._ready = asyncio.Event()
        self._command_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._setpoint_callbacks: set[SetpointCallback] = set()
        self._availability_callbacks: set[AvailabilityCallback] = set()
        self._online_callbacks: set[OnlineCallback] = set()
        self._measurement_callbacks: set[MeasurementCallback] = set()
        self._reconnect_callbacks: set[ReconnectCallback] = set()
        self._radio_callbacks: set[RadioCallback] = set()
        self._weather_callbacks: set[WeatherCallback] = set()
        self._diagnostic_callbacks: set[DiagnosticCallback] = set()
        self._available = False
        self._online = False
        self._has_connected = False
        self._reconnect_count = 0
        self._websocket_upgrade_failures = 0
        self._last_message_monotonic: float | None = None
        self._message_count = 0
        self._diagnostic_state: dict[str, Any] = {"connection_state": "starting"}
        self._connection_supervisor = DHEConnectionSupervisor()
        self._reconnect_grace_task: asyncio.Task[None] | None = None
        self._runtime_parser_stats: dict[str, int] = {}
        self._last_runtime_parser_category: str | None = None
        self._last_setpoint: float | None = None
        self._last_measurements: dict[int, MeasurementValue] = {}
        self._last_measurement_attributes: dict[int, dict[str, Any]] = {}
        self._last_app_values: dict[str, Any] = {}
        self._last_radio_state: dict[str, Any] = {}
        self._last_radio_stations: list[dict[str, Any]] = []
        self._last_radio_favorites: list[dict[str, Any]] = []
        self._last_radio_catalogs: dict[str, list[str]] = {
            field: [] for field in RADIO_CATALOG_FIELDS
        }
        self._last_radio_genres: list[str] = []
        self._radio_catalog_generations: dict[str, int] = dict.fromkeys(
            RADIO_CATALOG_FIELDS,
            0,
        )
        self._radio_stations_generation = 0
        self._radio_favorites_generation = 0
        self._radio_genres_generation = 0
        self._last_weather_state: dict[str, Any] = {}
        self._weather_search_generation = 0
        self._weather_favorites_generation = 0
        self._weather_countries_generation = 0
        self._last_weather_countries: list[dict[str, Any]] = []
        self._last_wellness_programs: tuple[dict[str, Any], ...] = ()
        self._wellness_program_callbacks: set[WellnessProgramsCallback] = set()
        self._last_saving_monitor_values: dict[str, Any] = {}
        self._last_device_info: dict[str, Any] = {}
        self._temperature_memory_ids_seen: set[int] = set()
        self._temperature_memory_generation = 0
        self._temperature_memory_full_list_seen = False
        self._nominal_power_kw = DEFAULT_NOMINAL_POWER_KW
        self._last_power_fraction: float | None = None
        self._pairing_active = False
        self._require_pairing_confirmation = False
        self._pairing_request_seen = False
        self._pairing_confirmed_success = False
        self._pairing_failed_explicit = False
        self._manual_pairing_requested = False
        self._pause_auto_reconnect_for_pairing = False
        self._pairing_retry_attempts = 0
        self._pending_setpoint_future: asyncio.Future[float] | None = None
        self._pending_expected_setpoint: float | None = None
        self._pending_write_future: asyncio.Future[ODBValue] | None = None
        self._pending_write_id: int | None = None
        self._setpoint_request_address = 0
        self._pending_write_expected: ODBValue | None = None
        self._pending_odb_read_deadlines: dict[int, float] = {}
        self._pending_app_read_deadlines: dict[str, float] = {}
        self._socketio_message_id = 1
        self._odb_value_handlers: dict[int, Callable[..., None]] = {
            ID_SETPOINT: self._handle_odb_setpoint_value,
            ID_WATER_FLOW: self._handle_odb_water_flow_value,
            ID_POWER_PERCENT: self._handle_odb_power_percent_value,
            ID_NOMINAL_POWER: self._handle_odb_nominal_power_value,
            ID_BATH_FILL_TARGET_VOLUME: self._handle_odb_bath_fill_target_value,
            ID_BATH_FILL_CURRENT_VOLUME: self._handle_odb_bath_fill_current_value,
            ID_PROTOCOL_VERSION: self._handle_odb_protocol_version_value,
            ID_WATER_HEATING_ENABLED: self._handle_odb_water_heating_enabled_value,
            ID_SCALD_PROTECTION_ACTIVE: self._handle_odb_scald_protection_active_value,
            ID_DEVICE_STATUS: self._handle_odb_device_status_value,
            ID_CO2_EMISSION_RAW: self._handle_odb_co2_emission_value,
            ID_CHILD_SAFETY_ACTIVE: self._handle_odb_child_safety_active_value,
        }

    @property
    def last_setpoint(self) -> float | None:
        return self._last_setpoint

    @property
    def available(self) -> bool:
        return self._available

    @property
    def online(self) -> bool:
        return self._online

    @property
    def reconnect_count(self) -> int:
        return self._reconnect_count

    @property
    def last_measurements(self) -> dict[int, MeasurementValue]:
        return dict(self._last_measurements)

    @property
    def last_measurement_attributes(self) -> dict[int, dict[str, Any]]:
        return {
            key: {
                attr_key: list(attr_value)
                if isinstance(attr_value, list)
                else attr_value
                for attr_key, attr_value in value.items()
            }
            for key, value in self._last_measurement_attributes.items()
        }

    @property
    def last_app_values(self) -> dict[str, Any]:
        return dict(self._last_app_values)

    @property
    def last_device_info(self) -> dict[str, Any]:
        return dict(self._last_device_info)

    @property
    def last_radio_state(self) -> dict[str, Any]:
        return self._copy_radio_state()

    @property
    def last_weather_state(self) -> dict[str, Any]:
        return self._copy_weather_state()

    @property
    def last_wellness_programs(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(program) for program in self._last_wellness_programs)

    @property
    def diagnostic_state(self) -> dict[str, Any]:
        return self._copy_diagnostic_state()

    @property
    def reconnect_supervisor_state(self) -> dict[str, Any]:
        return self._connection_supervisor.diagnostic_state()

    @property
    def transport_statistics(self) -> dict[str, int]:
        return {
            "websocket_upgrade_failures": self._websocket_upgrade_failures,
        }

    @property
    def runtime_parser_statistics(self) -> dict[str, Any]:
        return {
            "message_count": self._message_count,
            "last_category": self._last_runtime_parser_category,
            "counts": dict(sorted(self._runtime_parser_stats.items())),
        }

    async def start(self) -> None:
        if self._runner and not self._runner.done():
            return
        self._stopped.clear()
        self._runner = self._create_background_task(
            self._run_loop(),
            "stiebel_dhe_connect_session_loop",
        )

    async def stop(self) -> None:
        self._stopped.set()
        self._update_diagnostics(connection_state="stopping")
        grace_task = self._reconnect_grace_task
        self._reconnect_grace_task = None
        if grace_task is not None:
            await cancel_task_if_pending(grace_task)
        runner = self._runner
        self._runner = None
        if runner:
            runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await runner
        if getattr(self, "_owns_session", False):
            await self._session.close()
        ctx = self._ctx
        self._ctx = None
        self._ready.clear()
        if ctx is not None:
            await self._close_session(ctx)
        self._set_online(False)
        self._set_available(False, immediate=True)
        self._update_diagnostics(connection_state="stopped")

    async def validate_setup_authentication(
        self, *, timeout_seconds: float = 180.0
    ) -> None:
        """Run a one-shot pairing/authentication check used during config setup."""
        self._stopped.clear()
        ctx: DHESession | None = None
        try:
            self._begin_manual_pairing(
                "setup_requested",
                "Initial setup pairing started; waiting for DHE confirmation.",
                notify=True,
            )
            await self._clear_token()
            ctx = await asyncio.wait_for(
                self._open_authenticated_session(
                    token_request_timeout_seconds=timeout_seconds,
                ),
                timeout=timeout_seconds,
            )
            await self._request_device_info(
                ctx,
                timeout_seconds=min(
                    DEVICE_INFO_REQUEST_TIMEOUT_SECONDS,
                    timeout_seconds,
                ),
            )
        finally:
            if ctx is not None:
                with _suppress_transport_errors():
                    await self._close_session(ctx)
            self._ctx = None
            self._ready.clear()
            self._set_online(False)
            self._set_available(False, immediate=True)

    async def repair_pairing(self) -> bool:
        """Discard the local pairing token and start a fresh pairing attempt."""
        async with self._command_lock:
            _LOGGER.info(
                "DHE pairing repair requested. Stored token will be cleared; "
                "confirm pairing on the DHE display when prompted."
            )
            self._begin_manual_pairing(
                "repair_requested",
                "Stored token cleared; waiting for DHE pairing confirmation.",
                notify=True,
            )
            await self._clear_token()
            was_running = self._runner is not None and not self._runner.done()
            if was_running:
                await self.stop()
            await self.start()
        return True

    async def request_measurement_refresh(
        self,
        *,
        odb_id: int | None = None,
        app_command: str | None = None,
    ) -> None:
        """Request one measurement again for an entity enabled at runtime."""
        if odb_id is None and app_command is None:
            return
        if odb_id == ID_PROTOCOL_VERSION:
            await self._request_web_interface_version()
            return

        async def _operation(ctx: DHESession) -> None:
            if app_command is not None:
                await self._request_app_value(ctx, app_command)
                return
            if odb_id is not None:
                await self._request_odb_value(ctx, odb_id)

        await self._run_command_without_reconnect_retry(
            "Could not refresh DHE measurement",
            _operation,
            timeout=10.0,
        )

    async def _run_loop(self) -> None:
        while not self._stopped.is_set():
            try:  # noqa: PERF203
                self._ctx = await self._open_authenticated_session()
                self._record_session_connected()
                self._cancel_reconnect_grace_timer()
                self._update_diagnostics(
                    connection_state="initializing",
                    next_reconnect_delay_seconds=None,
                    ping_interval_seconds=self._ctx.ping_interval,
                    session_id=self._ctx.sid,
                    websocket_sid=self._ctx.websocket_sid,
                )
                self._set_online(True)
                await self._request_initial_values(self._ctx)
                await self._wait_for_initial_runtime_values(self._ctx)
                self._ready.set()
                self._set_available(True)
                self._update_diagnostics(connection_state="connected")
                while not self._stopped.is_set() and self._ctx is not None:
                    for event in await self._read_events_once(self._ctx):
                        await self._handle_runtime_event(event)
            except asyncio.CancelledError:  # noqa: PERF203
                raise
            except DHEAuthError as err:
                if await self._handle_auth_failure(err):
                    return
            except _DHE_TRANSPORT_EXCEPTIONS as err:
                if await self._handle_transport_reconnect(err):
                    return
            except RuntimeError as err:
                err = _runtime_transport_error_or_raise(err)
                if await self._handle_transport_reconnect(err):
                    return

    async def _handle_transport_reconnect(self, err: Exception) -> bool:
        """Update state and pause before reconnecting after transport failures."""
        self._clear_pending_future(err)
        self._clear_pending_write_future(err)
        self._ready.clear()
        ctx = self._ctx
        self._ctx = None
        reconnect_delay = self._mark_reconnecting(_diagnostic_error(err))
        if ctx is not None:
            await self._close_session(ctx)
        if self._pause_auto_reconnect_for_pairing:
            self._set_available(False, immediate=True)
            self._update_diagnostics(
                connection_state="pairing_failed_waiting_manual_retry",
                last_reconnect_reason=(
                    "Pairing failed; waiting for manual retry via 'Pairing erneuern'."
                ),
                next_reconnect_delay_seconds=None,
            )
            await self._stopped.wait()
            return True
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stopped.wait(), timeout=reconnect_delay)
        return False

    async def _handle_auth_failure(self, err: DHEAuthError) -> bool:
        """Mark stored-token failures and wait for Home Assistant reauth."""
        self._clear_pending_future(err)
        self._clear_pending_write_future(err)
        self._ready.clear()
        ctx = self._ctx
        self._ctx = None
        if ctx is not None:
            await self._close_session(ctx)
        self._set_online(False)
        self._set_available(False, immediate=True)
        self._update_diagnostics(
            connection_state="auth_failed",
            auth_failure=True,
            last_reconnect_reason=_diagnostic_error(err),
            next_reconnect_delay_seconds=None,
        )
        await self._stopped.wait()
        return True

    async def _request_setpoint(self, ctx: DHESession) -> None:
        await self._request_odb_value(ctx, ID_SETPOINT)

    async def _request_initial_values(self, ctx: DHESession) -> None:
        await self._request_web_interface_version()
        for odb_id in INITIAL_VALUE_IDS:
            await self._request_odb_value(ctx, odb_id)
        for command in APP_TIMER_REQUEST_COMMANDS:
            await self._request_app_value(ctx, command)
        for command in CONSUMPTION_REQUEST_COMMANDS:
            await self._request_app_value(ctx, command)
        for odb_id in OPTIONAL_STARTUP_ODB_IDS:
            await self._request_optional_odb_value(ctx, odb_id)
        for command in OPTIONAL_STARTUP_APP_REQUEST_COMMANDS:
            await self._request_optional_app_value(ctx, command)

    async def _request_device_info(
        self,
        ctx: DHESession,
        *,
        timeout_seconds: float = DEVICE_INFO_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        for command in DEVICE_INFO_REQUEST_COMMANDS:
            await self._request_app_value(ctx, command)
        if self._has_device_identity():
            return

        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while time.monotonic() < deadline:
            timeout = max(0.1, deadline - time.monotonic())
            try:
                events = await asyncio.wait_for(
                    self._read_events_once(ctx),
                    timeout=timeout,
                )
            except TimeoutError:
                return
            for event in events:
                await self._handle_runtime_event(event)
            if self._has_device_identity():
                return

    def _has_device_identity(self) -> bool:
        return bool(
            self._last_device_info.get("wlan_mac")
            or self._last_device_info.get("bluetooth_mac")
            or self._last_device_info.get("device_id")
        )

    async def _request_odb_value(self, ctx: DHESession, odb_id: int) -> None:
        self._mark_odb_read_requested(odb_id)
        sent = False
        try:
            await self._send_ste_command(
                ctx,
                ODB_GET_COMMAND,
                {"id": odb_id, "value": ""},
            )
            sent = True
        finally:
            if not sent:
                self._consume_odb_read_request(odb_id)

    async def _request_app_value(self, ctx: DHESession, command: str) -> None:
        track_radio_readback = command.startswith(f"get:{RADIO_PATH}:")
        if track_radio_readback:
            self._mark_app_read_requested(command)
        sent = False
        try:
            await self._send_ste_command(ctx, command, "")
            sent = True
        finally:
            if track_radio_readback and not sent:
                self._consume_app_read_request(command)

    async def _send_ste_command(
        self, ctx: DHESession, command: str, value: Any
    ) -> None:
        await self._post_packet(
            ctx,
            self._message_packet({"command": command, "value": value}),
        )

    async def _request_optional_odb_value(self, ctx: DHESession, odb_id: int) -> None:
        with contextlib.suppress(DHEError):
            await self._request_odb_value(ctx, odb_id)

    async def _request_optional_app_value(self, ctx: DHESession, command: str) -> None:
        with contextlib.suppress(DHEError):
            await self._request_app_value(ctx, command)

    async def _wait_for_initial_runtime_values(self, ctx: DHESession) -> None:
        """Wait until the DHE returns at least one runtime startup value."""
        if self._has_runtime_startup_proof():
            return
        deadline = time.monotonic() + RUNTIME_STARTUP_PROOF_TIMEOUT_SECONDS
        while time.monotonic() < deadline and not self._stopped.is_set():
            timeout = max(0.1, min(1.0, deadline - time.monotonic()))
            try:
                events = await asyncio.wait_for(
                    self._read_events_once(ctx),
                    timeout=timeout,
                )
            except TimeoutError:
                continue
            for event in events:
                await self._handle_runtime_event(event)
            if self._has_runtime_startup_proof():
                return
        raise DHEAuthError(
            "DHE authenticated but did not return startup values; "
            "reauthentication is required"
        )

    def _has_runtime_startup_proof(self) -> bool:
        """Return whether the authenticated runtime session produced DHE data."""
        return any(
            odb_id in self._last_measurements
            for odb_id in RUNTIME_STARTUP_PROOF_IDS
        )

    def _new_setpoint_future(
        self, expected: float | None = None
    ) -> asyncio.Future[float]:
        self._clear_pending_future(None)
        future: asyncio.Future[float] = self.hass.loop.create_future()
        self._pending_setpoint_future = future
        self._pending_expected_setpoint = expected
        return future

    def _clear_pending_future(self, err: Exception | None) -> None:
        future = self._pending_setpoint_future
        self._pending_setpoint_future = None
        self._pending_expected_setpoint = None
        if future is not None and not future.done():
            if err is not None:
                future.set_exception(err)
            else:
                future.cancel()

    def _new_write_future(
        self, odb_id: int, expected: ODBValue | None = None
    ) -> asyncio.Future[ODBValue]:
        self._clear_pending_write_future(None)
        future: asyncio.Future[ODBValue] = self.hass.loop.create_future()
        self._pending_write_future = future
        self._pending_write_id = int(odb_id)
        self._pending_write_expected = expected
        return future

    def _clear_pending_write_future(self, err: Exception | None) -> None:
        future = self._pending_write_future
        self._pending_write_future = None
        self._pending_write_id = None
        self._pending_write_expected = None
        if future is not None and not future.done():
            if err is not None:
                future.set_exception(err)
            else:
                future.cancel()


if TYPE_CHECKING:

    def _assert_client_mixin_contracts(client: DHEClient) -> None:
        """Keep the concrete client structurally compatible with mixin protocols."""
        command: DHEClientCommandContext = client
        connection: DHEClientConnectionContext = client
        diagnostics: DHEClientDiagnosticsContext = client
        runtime: DHEClientRuntimeContext = client
        transport: DHEClientTransportContext = client
        del command, connection, diagnostics, runtime, transport
