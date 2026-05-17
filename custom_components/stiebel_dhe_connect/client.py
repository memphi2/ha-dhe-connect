"""Persistent local Socket.IO/Engine.IO v3 client for Stiebel DHE Connect."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import random
from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client_command_runner import DHEClientCommandRunnerMixin
from .client_commands import DHEClientCommandsMixin
from .client_constants import (
    AVAILABILITY_DROP_GRACE_SECONDS,
    DEFAULT_NOMINAL_POWER_KW,
)
from .client_diagnostics import diagnostic_error as _diagnostic_error
from .client_errors import (
    DHE_TRANSPORT_EXCEPTIONS as _DHE_TRANSPORT_EXCEPTIONS,
    runtime_transport_error_or_raise as _runtime_transport_error_or_raise,
    suppress_transport_errors as _suppress_transport_errors,
)
from .client_pairing import DHEClientPairingMixin
from .client_runtime import DHEClientRuntimeMixin
from .client_transport import DHEClientTransportMixin
from .client_types import (
    AvailabilityCallback,
    CallbackRemover,
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
)
from .connection_helpers import host_for_url as _host_for_url
from .protocol import (
    APP_TIMER_REQUEST_COMMANDS,
    CONSUMPTION_REQUEST_COMMANDS,
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
    TEMPERATURE_MEMORY_SLOT_MEASUREMENTS,
)

_LOGGER = logging.getLogger(__name__)


class DHEClient(
    DHEClientPairingMixin,
    DHEClientCommandsMixin,
    DHEClientCommandRunnerMixin,
    DHEClientRuntimeMixin,
    DHEClientTransportMixin,
):
    """Persistent Engine.IO v3 WebSocket client for DHE Connect."""

    def __init__(self, hass: HomeAssistant, host: str, port: int, token_file: str, name: str) -> None:
        self.hass = hass
        normalized_host = host.strip().removeprefix("http://").removeprefix("https://").rstrip("/")
        if normalized_host.startswith("[") and normalized_host.endswith("]"):
            normalized_host = normalized_host[1:-1].strip()
        self.host = normalized_host
        self._url_host = _host_for_url(self.host)
        self.port = int(port)
        self.name = name
        self.legacy_device_identifier: str | None = None
        self.base_url = f"http://{self._url_host}:{self.port}"
        self.token_path = token_file if os.path.isabs(token_file) else hass.config.path(token_file)
        self._session = async_get_clientsession(hass)
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
        self._last_message_monotonic: float | None = None
        self._message_count = 0
        self._diagnostic_state: dict[str, Any] = {"connection_state": "starting"}
        self._availability_drop_task: asyncio.Task[None] | None = None
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
        self._pending_write_expected: ODBValue | None = None
        self._pending_odb_read_deadlines: dict[int, float] = {}
        self._socketio_message_id = random.randint(1, 99)
        self._odb_value_handlers: dict[int, Callable[[Any], None]] = {
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
                attr_key: list(attr_value) if isinstance(attr_value, list) else attr_value
                for attr_key, attr_value in value.items()
            }
            for key, value in self._last_measurement_attributes.items()
        }

    @property
    def last_app_values(self) -> dict[str, Any]:
        return dict(self._last_app_values)

    @property
    def last_radio_state(self) -> dict[str, Any]:
        return self._copy_radio_state()

    @property
    def last_weather_state(self) -> dict[str, Any]:
        return self._copy_weather_state()

    @property
    def diagnostic_state(self) -> dict[str, Any]:
        return self._copy_diagnostic_state()

    def add_setpoint_callback(self, callback: SetpointCallback) -> CallbackRemover:
        remove = self._add_callback(self._setpoint_callbacks, callback)
        if self._last_setpoint is not None:
            self._call_callback("setpoint", callback, self._last_setpoint)
        return remove

    def add_availability_callback(self, callback: AvailabilityCallback) -> CallbackRemover:
        remove = self._add_callback(self._availability_callbacks, callback)
        self._call_callback("availability", callback, self._available)
        return remove

    def add_online_callback(self, callback: OnlineCallback) -> CallbackRemover:
        remove = self._add_callback(self._online_callbacks, callback)
        self._call_callback("online", callback, self._online)
        return remove

    def add_measurement_callback(self, callback: MeasurementCallback) -> CallbackRemover:
        remove = self._add_callback(self._measurement_callbacks, callback)
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

    def add_diagnostic_callback(self, callback: DiagnosticCallback) -> CallbackRemover:
        remove = self._add_callback(self._diagnostic_callbacks, callback)
        self._call_callback("diagnostic", callback, self._copy_diagnostic_state())
        return remove

    @staticmethod
    def _add_callback(callbacks: set[Callable[..., None]], callback: Callable[..., None]) -> CallbackRemover:
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
            DHEClient._log_callback_exception(callback_name)

    @staticmethod
    def _log_callback_exception(callback_name: str) -> None:
        _LOGGER.debug("DHE %s callback raised an exception", callback_name, exc_info=True)

    async def start(self) -> None:
        if self._runner and not self._runner.done():
            return
        self._stopped.clear()
        self._runner = self._create_background_task(
            self._run_loop(),
            "stiebel_dhe_connect_session_loop",
        )

    def _create_background_task(self, coro: Any, name: str) -> asyncio.Task[Any]:
        create_background_task = getattr(self.hass, "async_create_background_task", None)
        if create_background_task is not None:
            return create_background_task(coro, name)
        return self.hass.async_create_task(coro, name=name)

    async def stop(self) -> None:
        self._stopped.set()
        self._update_diagnostics(connection_state="stopping")
        runner = self._runner
        self._runner = None
        if runner:
            runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await runner
        ctx = self._ctx
        self._ctx = None
        self._ready.clear()
        if ctx is not None:
            await self._close_session(ctx)
        self._set_online(False)
        self._set_available(False, immediate=True)
        self._update_diagnostics(connection_state="stopped")

    async def validate_setup_authentication(self, *, timeout_seconds: float = 180.0) -> None:
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
                self._update_diagnostics(
                    connection_state="connected",
                    ping_interval_seconds=self._ctx.ping_interval,
                    session_id=self._ctx.sid,
                    websocket_sid=self._ctx.websocket_sid,
                )
                self._set_online(True)
                self._ready.set()
                self._set_available(True)
                await self._request_initial_values(self._ctx)
                while not self._stopped.is_set() and self._ctx is not None:
                    for event in await self._read_events_once(self._ctx):
                        await self._handle_runtime_event(event)
            except asyncio.CancelledError:  # noqa: PERF203
                raise
            except _DHE_TRANSPORT_EXCEPTIONS as err:
                if await self._handle_transport_reconnect(err):
                    return
            except RuntimeError as err:
                err = _runtime_transport_error_or_raise(err)
                if await self._handle_transport_reconnect(err):
                    return

    async def _handle_transport_reconnect(self, err: Exception) -> bool:
        """Update state and pause before reconnecting after transport failures."""
        self._update_diagnostics(
            connection_state="reconnecting",
            last_reconnect_reason=_diagnostic_error(err),
        )
        self._clear_pending_future(err)
        self._clear_pending_write_future(err)
        self._ready.clear()
        self._set_online(False)
        self._set_available(False)
        ctx = self._ctx
        self._ctx = None
        if ctx is not None:
            await self._close_session(ctx)
        if self._pause_auto_reconnect_for_pairing:
            self._update_diagnostics(
                connection_state="pairing_failed_waiting_manual_retry",
                last_reconnect_reason=(
                    "Pairing failed; waiting for manual retry via "
                    "'Pairing erneuern'."
                ),
            )
            await self._stopped.wait()
            return True
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stopped.wait(), timeout=10)
        return False

    async def _request_setpoint(self, ctx: DHESession) -> None:
        await self._request_odb_value(ctx, ID_SETPOINT)

    async def _request_initial_values(self, ctx: DHESession) -> None:
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
        await self._send_ste_command(ctx, command, "")

    async def _send_ste_command(self, ctx: DHESession, command: str, value: Any) -> None:
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

    def _new_setpoint_future(self, expected: float | None = None) -> asyncio.Future[float]:
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

    def _new_write_future(self, odb_id: int, expected: ODBValue | None = None) -> asyncio.Future[ODBValue]:
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

    def _set_available(self, available: bool, *, immediate: bool = False) -> None:
        if available:
            self._cancel_delayed_unavailable()
            self._emit_availability(True)
            return

        if immediate:
            self._cancel_delayed_unavailable()
            self._emit_availability(False)
            return

        if self._availability_drop_task is not None and not self._availability_drop_task.done():
            return
        self._availability_drop_task = self.hass.async_create_task(
            self._delayed_set_unavailable(),
            name="stiebel_dhe_connect_delayed_unavailable",
        )

    def _emit_availability(self, available: bool) -> None:
        if self._available == available:
            return
        self._available = available
        self._notify_callbacks(
            "availability",
            self._availability_callbacks,
            available,
        )

    def _set_online(self, online: bool) -> None:
        if self._online == online:
            return
        self._online = online
        self._notify_callbacks("online", self._online_callbacks, online)

    def _cancel_delayed_unavailable(self) -> None:
        task = self._availability_drop_task
        self._availability_drop_task = None
        if task is not None and not task.done():
            task.cancel()

    async def _delayed_set_unavailable(self) -> None:
        try:
            await asyncio.sleep(AVAILABILITY_DROP_GRACE_SECONDS)
            if self._ctx is None and not self._ready.is_set() and not self._stopped.is_set():
                self._emit_availability(False)
        except asyncio.CancelledError:
            return
        finally:
            self._availability_drop_task = None
