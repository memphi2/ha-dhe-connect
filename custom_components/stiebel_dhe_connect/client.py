"""Persistent local Socket.IO/Engine.IO v3 client for Stiebel DHE Connect."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

NS = "1.0.0"
ODB_GET_COMMAND = "get:ste.common.odb:value"
ODB_SET_COMMAND = "set:ste.common.odb:value"
ODB_ASSIGN_COMMAND = "assign:ste.common.odb:value"

ID_SETPOINT = 0
ID_BATH_FILL_ACTIVE = 1
ID_WELLNESS_SHOWER_PROGRAM = 2
ID_BATH_FILL_TARGET_VOLUME = 3
ID_MAX_TEMPERATURE = 5
ID_ECO_MODE = 6
ID_ECO_FLOW_LIMIT = 7
ID_STOP_PROGRAM = 10
ID_WATER_FLOW = 15
ID_POWER = 16
ID_CONFIGURED_POWER = 20
ID_SET_REQ = 66
ID_BRUSH_TIMER_ACTIVATION = 1001
ID_BRUSH_TIMER_DURATION = 1002
ID_BRUSH_TIMER_REMAINING = 1003
ID_SHOWER_TIMER_ACTIVATION = 1011
ID_SHOWER_TIMER_DURATION = 1012
ID_SHOWER_TIMER_REMAINING = 1013
ID_WATER_CONSUMPTION_WEEK = 1021
ID_WATER_CONSUMPTION_YEAR = 1022
ID_WATER_CONSUMPTION_YEARS = 1023
ID_ENERGY_CONSUMPTION_WEEK = 1031
ID_ENERGY_CONSUMPTION_YEAR = 1032
ID_ENERGY_CONSUMPTION_YEARS = 1033
DEFAULT_CONFIGURED_POWER_KW = 24.0
COMMAND_CONFIRMATION_TIMEOUT = 12.0
COMMAND_READBACK_INTERVAL = 1.0
APP_COMMAND_CONFIRMATION_TIMEOUT = 3.0
AVAILABILITY_DROP_GRACE_SECONDS = 20.0
INITIAL_VALUE_IDS = (
    ID_SETPOINT,
    ID_BATH_FILL_ACTIVE,
    ID_BATH_FILL_TARGET_VOLUME,
    ID_WELLNESS_SHOWER_PROGRAM,
    ID_MAX_TEMPERATURE,
    ID_ECO_MODE,
    ID_ECO_FLOW_LIMIT,
    ID_STOP_PROGRAM,
    ID_WATER_FLOW,
    ID_POWER,
    ID_CONFIGURED_POWER,
)

BRUSH_TIMER_PATH = "ste.app.brushTimer"
SHOWER_TIMER_PATH = "ste.app.showerTimer"
TIMER_PATH_IDS = {
    BRUSH_TIMER_PATH: {
        "activation": ID_BRUSH_TIMER_ACTIVATION,
        "durationMilliseconds": ID_BRUSH_TIMER_DURATION,
        "remainingMilliseconds": ID_BRUSH_TIMER_REMAINING,
    },
    SHOWER_TIMER_PATH: {
        "activation": ID_SHOWER_TIMER_ACTIVATION,
        "durationMilliseconds": ID_SHOWER_TIMER_DURATION,
        "remainingMilliseconds": ID_SHOWER_TIMER_REMAINING,
    },
}
APP_TIMER_SET_COMMANDS = {
    f"set:{path}:{property_name}"
    for path, property_ids in TIMER_PATH_IDS.items()
    for property_name in property_ids
}
APP_TIMER_ASSIGN_COMMANDS = {
    f"assign:{path}:{property_name}"
    for path, property_ids in TIMER_PATH_IDS.items()
    for property_name in property_ids
    if property_name != "remainingMilliseconds"
}
APP_TIMER_RESET_COMMANDS = {
    f"{action}:{path}:reset"
    for action in ("set", "assign")
    for path in TIMER_PATH_IDS
}
APP_TIMER_REQUEST_COMMANDS = tuple(
    f"get:{path}:{property_name}"
    for path, property_ids in TIMER_PATH_IDS.items()
    for property_name in property_ids
)
CONSUMPTION_COMMAND_IDS = {
    "set:ste.app.consumption:waterWeek": ID_WATER_CONSUMPTION_WEEK,
    "set:ste.app.consumption:waterYear": ID_WATER_CONSUMPTION_YEAR,
    "set:ste.app.consumption:waterYears": ID_WATER_CONSUMPTION_YEARS,
    "set:ste.app.consumption:energyWeek": ID_ENERGY_CONSUMPTION_WEEK,
    "set:ste.app.consumption:energyYear": ID_ENERGY_CONSUMPTION_YEAR,
    "set:ste.app.consumption:energyYears": ID_ENERGY_CONSUMPTION_YEARS,
}
CONSUMPTION_REQUEST_COMMANDS = tuple(
    command.replace("set:", "get:", 1) for command in CONSUMPTION_COMMAND_IDS
)


ODBValue = bool | float
SetpointCallback = Callable[[float], None]
AvailabilityCallback = Callable[[bool], None]
MeasurementCallback = Callable[[int, ODBValue], None]
CallbackRemover = Callable[[], None]


class DHEError(Exception):
    """Base DHE exception."""


class DHESessionClosed(DHEError):
    """DHE closed the Socket.IO namespace/session."""


@dataclass
class DHEEvent:
    """Parsed Socket.IO event."""

    name: str
    data: Any


@dataclass
class DHESession:
    """Open Engine.IO/Socket.IO polling session context."""

    sid: str
    url_token: str
    websocket_sid: str | None = None


def _round_to_half_c(value: float) -> float:
    return round(value * 2.0) / 2.0


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _c_to_raw_tenths(value: float) -> int:
    return int(round(value * 10.0))


def _raw_tenths_to_c(value: int | float) -> float:
    return float(value) / 10.0


def _raw_to_float(value: Any) -> float:
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
    return float(value)


def _build_req66(temp_c: float, addr: int) -> int:
    raw = _c_to_raw_tenths(temp_c) & 1023
    return int(raw | ((addr & 0xFF) << 10))


def _raw_to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "on", "yes"}:
            return True
        if lowered in {"false", "off", "no", ""}:
            return False
    return bool(int(_raw_to_float(value)))


def _values_equal(a: ODBValue | None, b: ODBValue | None) -> bool:
    if a is None or b is None:
        return a is b
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) is bool(b)
    return abs(float(a) - float(b)) < 0.001


class DHEClient:
    """Persistent Engine.IO v3 long-polling client for DHE Connect."""

    def __init__(self, hass: HomeAssistant, host: str, port: int, token_file: str, name: str) -> None:
        self.hass = hass
        self.host = host.strip().removeprefix("http://").removeprefix("https://").rstrip("/")
        self.port = int(port)
        self.name = name
        self.base_url = f"http://{self.host}:{self.port}"
        self.token_path = token_file if os.path.isabs(token_file) else hass.config.path(token_file)
        self._session = async_get_clientsession(hass)
        self._ctx: DHESession | None = None
        self._token: str | None = None
        self._runner: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        self._ready = asyncio.Event()
        self._command_lock = asyncio.Lock()
        self._setpoint_callbacks: list[SetpointCallback] = []
        self._availability_callbacks: list[AvailabilityCallback] = []
        self._measurement_callbacks: list[MeasurementCallback] = []
        self._available = False
        self._availability_drop_task: asyncio.Task[None] | None = None
        self._last_setpoint: float | None = None
        self._last_measurements: dict[int, ODBValue] = {}
        self._last_measurement_attributes: dict[int, dict[str, Any]] = {}
        self._configured_power_kw = DEFAULT_CONFIGURED_POWER_KW
        self._last_power_fraction: float | None = None
        self._pending_setpoint_future: asyncio.Future[float] | None = None
        self._pending_expected_setpoint: float | None = None
        self._pending_write_future: asyncio.Future[ODBValue] | None = None
        self._pending_write_id: int | None = None
        self._pending_write_expected: ODBValue | None = None
        self._socketio_message_id = random.randint(1, 99)

    @property
    def last_setpoint(self) -> float | None:
        return self._last_setpoint

    @property
    def available(self) -> bool:
        return self._available

    @property
    def last_measurements(self) -> dict[int, ODBValue]:
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

    def add_setpoint_callback(self, callback: SetpointCallback) -> CallbackRemover:
        return self._add_callback(self._setpoint_callbacks, callback)

    def add_availability_callback(self, callback: AvailabilityCallback) -> CallbackRemover:
        return self._add_callback(self._availability_callbacks, callback)

    def add_measurement_callback(self, callback: MeasurementCallback) -> CallbackRemover:
        return self._add_callback(self._measurement_callbacks, callback)

    @staticmethod
    def _add_callback(callbacks: list[Callable[..., None]], callback: Callable[..., None]) -> CallbackRemover:
        callbacks.append(callback)

        def _remove_callback() -> None:
            try:
                callbacks.remove(callback)
            except ValueError:
                pass

        return _remove_callback

    async def start(self) -> None:
        if self._runner and not self._runner.done():
            return
        self._stopped.clear()
        create_background_task = getattr(self.hass, "async_create_background_task", None)
        if create_background_task is not None:
            self._runner = create_background_task(self._run_loop(), "stiebel_dhe_connect_session_loop")
        else:
            self._runner = self.hass.async_create_task(self._run_loop(), name="stiebel_dhe_connect_session_loop")

    async def stop(self) -> None:
        self._stopped.set()
        runner = self._runner
        self._runner = None
        if runner:
            runner.cancel()
            try:
                await runner
            except asyncio.CancelledError:
                pass
        ctx = self._ctx
        self._ctx = None
        self._ready.clear()
        if ctx is not None:
            await self._close_session(ctx)
        self._set_available(False, immediate=True)

    async def set_temperature(self, temperature: float) -> float:
        requested = _round_to_half_c(_clamp(float(temperature), 20.0, 60.0))
        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    addr = random.randint(1, 63)
                    req_value = _build_req66(requested, addr)
                    future = self._new_setpoint_future(requested)
                    await self._post_packet(ctx, self._message_packet({
                        "command": ODB_ASSIGN_COMMAND,
                        "value": {"id": ID_SET_REQ, "value": req_value},
                    }))
                    readback = await self._wait_for_setpoint_confirmation(ctx, future)
                    if abs(readback - requested) < 0.01:
                        return readback
                    raise DHEError(f"readback was {readback:.1f} C, expected {requested:.1f} C")
                except Exception as err:  # noqa: BLE001
                    self._clear_pending_future(None)
                    if attempt == 0:
                        await self._force_reconnect()
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not set DHE setpoint: {err}") from err
        raise DHEError("Could not set DHE setpoint")

    async def write_odb_value(self, odb_id: int, value: Any) -> ODBValue:
        expected = self._convert_odb_value(odb_id, value)
        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    future = self._new_write_future(odb_id, expected)
                    await self._post_packet(ctx, self._message_packet({
                        "command": ODB_ASSIGN_COMMAND,
                        "value": {"id": int(odb_id), "value": value},
                    }))
                    confirmed = await self._wait_for_write_confirmation(ctx, future, odb_id)
                    if _values_equal(confirmed, expected):
                        return confirmed
                    raise DHEError(f"write confirmation was {confirmed!r}, expected {expected!r}")
                except Exception as err:  # noqa: BLE001
                    self._clear_pending_write_future(None)
                    if attempt == 0:
                        await self._force_reconnect()
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not write DHE ODB id {odb_id}: {err}") from err
        raise DHEError(f"Could not write DHE ODB id {odb_id}")

    async def start_bath_fill(self) -> bool:
        return bool(await self.write_odb_value(ID_BATH_FILL_ACTIVE, True))

    async def stop_bath_fill(self) -> bool:
        return bool(await self.write_odb_value(ID_BATH_FILL_ACTIVE, False))

    async def set_bath_fill_target_volume(self, liters: float) -> float:
        requested = int(round(_clamp(float(liters), 1.0, 300.0)))
        return float(await self.write_odb_value(ID_BATH_FILL_TARGET_VOLUME, requested))

    async def set_maximum_temperature(self, temperature: float) -> float:
        requested = _round_to_half_c(_clamp(float(temperature), 30.0, 50.0))
        return float(await self.write_odb_value(ID_MAX_TEMPERATURE, _c_to_raw_tenths(requested)))

    async def set_eco_mode(self, enabled: bool) -> bool:
        return bool(await self.write_odb_value(ID_ECO_MODE, bool(enabled)))

    async def set_eco_flow_limit(self, liters_per_minute: float) -> float:
        requested_l_min = int(round(_clamp(float(liters_per_minute), 6.0, 8.0)))
        raw_value = requested_l_min * 10
        return float(await self.write_odb_value(ID_ECO_FLOW_LIMIT, raw_value))


    async def set_wellness_cold_prevention(self, enabled: bool) -> bool:
        if enabled:
            await self.write_odb_value(ID_WELLNESS_SHOWER_PROGRAM, 1)
            return True
        await self.write_odb_value(ID_STOP_PROGRAM, True)
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
            ID_BRUSH_TIMER_REMAINING,
        )

    async def reset_shower_timer(self) -> bool:
        return await self._reset_app_timer(
            SHOWER_TIMER_PATH,
            ID_SHOWER_TIMER_ACTIVATION,
            ID_SHOWER_TIMER_REMAINING,
        )

    async def _set_app_timer_duration_minutes(self, path: str, measurement_id: int, minutes: float) -> float:
        requested_minutes = int(round(_clamp(float(minutes), 1.0, 20.0)))
        milliseconds = requested_minutes * 60000
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

    async def _reset_app_timer(self, path: str, activation_id: int, remaining_id: int) -> bool:
        await self._write_app_value(
            f"assign:{path}:reset",
            True,
            remaining_id,
            0.0,
        )
        self._handle_measurement(remaining_id, 0.0, force_update=True)
        self._handle_measurement(activation_id, False, force_update=True)
        return True

    async def _write_app_value(self, command: str, value: Any, measurement_id: int, expected: ODBValue) -> ODBValue:
        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    future = self._new_write_future(measurement_id, expected)
                    await self._post_packet(ctx, self._message_packet({"command": command, "value": value}))
                    try:
                        return await self._wait_for_app_write_confirmation(future)
                    except TimeoutError as err:
                        self._clear_pending_write_future(None)
                        raise DHEError(
                            f"No DHE app confirmation for {command} within "
                            f"{APP_COMMAND_CONFIRMATION_TIMEOUT:.1f}s"
                        ) from err
                except Exception as err:  # noqa: BLE001
                    self._clear_pending_write_future(None)
                    if attempt == 0:
                        await self._force_reconnect()
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not write DHE app command {command}: {err}") from err
        raise DHEError(f"Could not write DHE app command {command}")

    async def _run_loop(self) -> None:
        while not self._stopped.is_set():
            try:
                self._ctx = await self._open_authenticated_session()
                self._ready.set()
                self._set_available(True)
                await self._request_initial_values(self._ctx)
                while not self._stopped.is_set() and self._ctx is not None:
                    for event in await self._read_events_once(self._ctx):
                        await self._handle_runtime_event(event)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("DHE persistent session failed: %s", err)
                self._clear_pending_future(err)
                self._clear_pending_write_future(err)
                self._ready.clear()
                self._set_available(False)
                ctx = self._ctx
                self._ctx = None
                if ctx is not None:
                    await self._close_session(ctx)
                try:
                    await asyncio.wait_for(self._stopped.wait(), timeout=10)
                except TimeoutError:
                    pass

    async def _open_authenticated_session(self) -> DHESession:
        token = await self._load_token()
        if not token:
            _LOGGER.info("No stored DHE token. Requesting new token; confirm pairing on DHE if prompted.")
            token = await self._request_initial_token()
            if not token:
                raise DHEError("No token received. Pairing may be required on the DHE.")
        ctx = await self._open_session(token)
        try:
            await self._post_packet(ctx, self._event_packet("token_request", {"token": token, "name": self.name}))
            deadline = time.monotonic() + 45.0
            last_nudge = 0.0
            while time.monotonic() < deadline and not self._stopped.is_set():
                for event in await self._read_events_once(ctx):
                    if event.name == "__closed":
                        raise DHESessionClosed("DHE closed Socket.IO session during authentication")
                    if event.name == "token_response" and isinstance(event.data, str) and len(event.data) > 20:
                        token = event.data
                        await self._save_token(token)
                        await self._post_packet(ctx, self._event_packet("authenticate", {"token": token}))
                    elif event.name == "authenticated":
                        return ctx
                    elif event.name == "pairing_request":
                        _LOGGER.info("DHE pairing requested. Confirm on the DHE if prompted.")
                    elif event.name == "pairing_result":
                        _LOGGER.debug("DHE pairing_result received: %s", event.data)
                if time.monotonic() - last_nudge > 0.9:
                    await self._post_packet(ctx, self._event_packet("token_request", {"token": token, "name": self.name}))
                    last_nudge = time.monotonic()
                await asyncio.sleep(0.25)
            raise DHEError("Auth timeout: no authenticated event received")
        except (asyncio.CancelledError, Exception):
            await self._close_session(ctx)
            raise

    async def _request_initial_token(self) -> str:
        ctx = await self._open_session("")
        try:
            await self._post_packet(ctx, self._event_packet("token_request", {"token": "", "name": self.name}))
            deadline = time.monotonic() + 120.0
            while time.monotonic() < deadline and not self._stopped.is_set():
                for event in await self._read_events_once(ctx):
                    if event.name == "__closed":
                        raise DHESessionClosed("DHE closed Socket.IO session while requesting token")
                    if event.name == "pairing_request":
                        _LOGGER.info("DHE pairing requested. Confirm on the DHE.")
                    if event.name == "token_response" and isinstance(event.data, str) and len(event.data) > 20:
                        await self._save_token(event.data)
                        return event.data
                await asyncio.sleep(0.3)
            raise DHEError("Token request timeout")
        finally:
            await self._close_session(ctx)

    async def _open_session(self, token_for_url: str) -> DHESession:
        open_payload = await self._get_text(self._poll_url(token_for_url, None, None))
        sid_match = re.search(r'"sid":"([^"]+)"', open_payload)
        if not sid_match:
            raise DHEError(f"Could not extract sid from open payload: {open_payload!r}")
        websocket_sid_match = re.search(r'"websocketSid":"([^"]+)"', open_payload)
        ctx = DHESession(
            sid=sid_match.group(1),
            url_token=token_for_url,
            websocket_sid=websocket_sid_match.group(1) if websocket_sid_match else None,
        )
        await self._post_packet(ctx, "40")
        await self._post_packet(ctx, f"40/{NS},")
        return ctx

    async def _close_session(self, ctx: DHESession) -> None:
        try:
            await self._post_packet(ctx, f"41/{NS}")
        except Exception:  # noqa: BLE001
            pass

    async def _force_reconnect(self) -> None:
        ctx = self._ctx
        self._ctx = None
        self._ready.clear()
        self._set_available(False)
        if ctx is not None:
            await self._close_session(ctx)

    async def _ensure_ready(self, timeout: float) -> None:
        if self._ctx is not None and self._available:
            return
        await asyncio.wait_for(self._ready.wait(), timeout=timeout)

    async def _handle_runtime_event(self, event: DHEEvent) -> None:
        if event.name == "__closed":
            raise DHESessionClosed("DHE closed Socket.IO session")
        if event.name != "message" or not isinstance(event.data, dict):
            return
        data = event.data
        command = data.get("command")
        value = data.get("value")
        if command in APP_TIMER_RESET_COMMANDS:
            self._handle_app_timer_reset(command)
            return
        if command in APP_TIMER_SET_COMMANDS | APP_TIMER_ASSIGN_COMMANDS:
            self._handle_app_timer_value(command, value)
            return
        if command in CONSUMPTION_COMMAND_IDS:
            self._handle_consumption_value(command, value)
            return
        if command not in {ODB_SET_COMMAND, ODB_ASSIGN_COMMAND} or not isinstance(value, dict):
            return
        try:
            odb_id = int(value.get("id", -1))
        except (TypeError, ValueError):
            return
        self._handle_odb_value(odb_id, value.get("value"))

    def _handle_app_timer_value(self, command: str, raw_value: Any) -> None:
        try:
            _action, path, property_name = command.split(":", 2)
            measurement_id = TIMER_PATH_IDS.get(path, {}).get(property_name)
            if measurement_id is None:
                return
            if property_name == "activation":
                self._handle_measurement(measurement_id, _raw_to_bool(raw_value))
            elif property_name in {"durationMilliseconds", "remainingMilliseconds"}:
                self._handle_measurement(measurement_id, _raw_to_float(raw_value) / 60000.0)
        except (TypeError, ValueError) as err:
            _LOGGER.debug("Ignoring invalid app timer value command=%s value=%r: %s", command, raw_value, err)

    def _handle_app_timer_reset(self, command: str) -> None:
        try:
            _action, path, _property_name = command.split(":", 2)
        except ValueError:
            return
        if path == BRUSH_TIMER_PATH:
            self._handle_measurement(ID_BRUSH_TIMER_REMAINING, 0.0, force_update=True)
            self._handle_measurement(ID_BRUSH_TIMER_ACTIVATION, False, force_update=True)
        elif path == SHOWER_TIMER_PATH:
            self._handle_measurement(ID_SHOWER_TIMER_REMAINING, 0.0, force_update=True)
            self._handle_measurement(ID_SHOWER_TIMER_ACTIVATION, False, force_update=True)

    def _handle_consumption_value(self, command: str, raw_value: Any) -> None:
        if not isinstance(raw_value, dict):
            return
        measurement_id = CONSUMPTION_COMMAND_IDS[command]
        raw_chart = raw_value.get("chart", [])
        if not isinstance(raw_chart, list):
            _LOGGER.debug("Ignoring invalid consumption chart command=%s value=%r", command, raw_value)
            return
        try:
            chart = [_raw_to_float(value) for value in raw_chart]
            cost_eur = _raw_to_float(raw_value["sum"]) if raw_value.get("sum") is not None else None
        except (TypeError, ValueError) as err:
            _LOGGER.debug("Ignoring invalid consumption value command=%s value=%r: %s", command, raw_value, err)
            return

        attributes = {
            "chart": chart,
            "cost_eur": cost_eur,
            "source_command": command,
        }
        previous_attributes = self._last_measurement_attributes.get(measurement_id)
        self._last_measurement_attributes[measurement_id] = attributes
        self._handle_measurement(
            measurement_id,
            sum(chart),
            force_update=previous_attributes != attributes,
        )

    def _handle_odb_value(self, odb_id: int, raw_value: Any) -> None:
        try:
            if odb_id == ID_SETPOINT:
                self._handle_setpoint(_raw_tenths_to_c(_raw_to_float(raw_value)))
            elif odb_id == ID_WATER_FLOW:
                self._handle_measurement(odb_id, _raw_to_float(raw_value) / 10.0)
            elif odb_id == ID_POWER:
                self._last_power_fraction = _raw_to_float(raw_value) / 100.0
                self._handle_measurement(odb_id, self._last_power_fraction * self._configured_power_kw)
            elif odb_id == ID_CONFIGURED_POWER:
                self._configured_power_kw = self._raw_configured_power_to_kw(_raw_to_float(raw_value))
                self._handle_measurement(odb_id, self._configured_power_kw)
                if self._last_power_fraction is not None:
                    self._handle_measurement(ID_POWER, self._last_power_fraction * self._configured_power_kw)
            elif odb_id in {
                ID_BATH_FILL_ACTIVE,
                ID_BATH_FILL_TARGET_VOLUME,
    ID_WELLNESS_SHOWER_PROGRAM,
                ID_MAX_TEMPERATURE,
                ID_ECO_MODE,
                ID_ECO_FLOW_LIMIT,
    ID_STOP_PROGRAM,
            }:
                self._handle_measurement(odb_id, self._convert_odb_value(odb_id, raw_value))
        except (TypeError, ValueError) as err:
            _LOGGER.debug("Ignoring invalid DHE ODB value id=%s value=%r: %s", odb_id, raw_value, err)

    def _handle_setpoint(self, value: float) -> None:
        previous = self._last_setpoint
        self._last_setpoint = value
        if previous is None or abs(previous - value) >= 0.01:
            for callback in tuple(self._setpoint_callbacks):
                callback(value)
        future = self._pending_setpoint_future
        expected = self._pending_expected_setpoint
        if future is not None and not future.done() and (expected is None or abs(value - expected) < 0.01):
            future.set_result(value)
            self._pending_setpoint_future = None
            self._pending_expected_setpoint = None

    def _handle_measurement(self, odb_id: int, value: ODBValue, *, force_update: bool = False) -> None:
        previous = self._last_measurements.get(odb_id)
        self._last_measurements[odb_id] = value
        self._maybe_complete_write_future(odb_id, value)
        if not force_update and previous is not None and _values_equal(previous, value):
            return
        for callback in tuple(self._measurement_callbacks):
            callback(odb_id, value)

    def _maybe_complete_write_future(self, odb_id: int, value: ODBValue) -> None:
        future = self._pending_write_future
        if future is None or future.done() or self._pending_write_id != odb_id:
            return
        expected = self._pending_write_expected
        if expected is None or _values_equal(value, expected):
            future.set_result(value)
            self._pending_write_future = None
            self._pending_write_id = None
            self._pending_write_expected = None

    async def _wait_for_setpoint_confirmation(
        self,
        ctx: DHESession,
        future: asyncio.Future[float],
    ) -> float:
        deadline = time.monotonic() + COMMAND_CONFIRMATION_TIMEOUT
        next_readback = 0.0
        while not future.done():
            now = time.monotonic()
            if now >= deadline:
                break
            if now >= next_readback:
                await self._request_setpoint(ctx)
                next_readback = now + COMMAND_READBACK_INTERVAL
            timeout = min(COMMAND_READBACK_INTERVAL, max(0.1, deadline - now))
            try:
                return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
            except TimeoutError:
                continue
        if future.done():
            return future.result()
        raise DHEError("setpoint confirmation timed out")

    async def _wait_for_write_confirmation(
        self,
        ctx: DHESession,
        future: asyncio.Future[ODBValue],
        odb_id: int,
    ) -> ODBValue:
        deadline = time.monotonic() + COMMAND_CONFIRMATION_TIMEOUT
        next_readback = 0.0
        while not future.done():
            now = time.monotonic()
            if now >= deadline:
                break
            if now >= next_readback:
                await self._request_odb_value(ctx, odb_id)
                next_readback = now + COMMAND_READBACK_INTERVAL
            timeout = min(COMMAND_READBACK_INTERVAL, max(0.1, deadline - now))
            try:
                return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
            except TimeoutError:
                continue
        if future.done():
            return future.result()
        raise DHEError(f"write confirmation timed out for DHE ODB id {odb_id}")

    async def _wait_for_app_write_confirmation(
        self,
        future: asyncio.Future[ODBValue],
    ) -> ODBValue:
        return await asyncio.wait_for(
            asyncio.shield(future),
            timeout=APP_COMMAND_CONFIRMATION_TIMEOUT,
        )

    @staticmethod
    def _convert_odb_value(odb_id: int, raw_value: Any) -> ODBValue:
        if odb_id in {ID_BATH_FILL_ACTIVE, ID_ECO_MODE}:
            return _raw_to_bool(raw_value)
        if odb_id == ID_MAX_TEMPERATURE:
            value = _raw_to_float(raw_value)
            if 300.0 <= value <= 500.0:
                return _raw_tenths_to_c(value)
            return value
        if odb_id == ID_ECO_FLOW_LIMIT:
            value = _raw_to_float(raw_value)
            if 60.0 <= value <= 80.0:
                return value / 10.0
            return value
        return _raw_to_float(raw_value)

    @staticmethod
    def _raw_configured_power_to_kw(raw: int | float) -> float:
        value = float(raw)
        if 18.0 <= value <= 24.0:
            return value
        if 180.0 <= value <= 240.0:
            return value / 10.0
        if 1800.0 <= value <= 2400.0:
            return value / 100.0
        _LOGGER.warning("Ignoring unexpected configured DHE power value from ODB id 20: %s", raw)
        return DEFAULT_CONFIGURED_POWER_KW

    async def _request_setpoint(self, ctx: DHESession) -> None:
        await self._request_odb_value(ctx, ID_SETPOINT)

    async def _request_initial_values(self, ctx: DHESession) -> None:
        for odb_id in INITIAL_VALUE_IDS:
            if odb_id != ID_CONFIGURED_POWER or odb_id not in self._last_measurements:
                await self._request_odb_value(ctx, odb_id)
        for command in APP_TIMER_REQUEST_COMMANDS:
            await self._request_app_value(ctx, command)
        for command in CONSUMPTION_REQUEST_COMMANDS:
            await self._request_app_value(ctx, command)

    async def _request_odb_value(self, ctx: DHESession, odb_id: int) -> None:
        await self._post_packet(
            ctx,
            self._message_packet({"command": ODB_GET_COMMAND, "value": {"id": odb_id, "value": ""}}),
        )

    async def _request_app_value(self, ctx: DHESession, command: str) -> None:
        await self._post_packet(ctx, self._message_packet({"command": command, "value": ""}))

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
        for callback in tuple(self._availability_callbacks):
            callback(available)

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

    async def _read_events_once(self, ctx: DHESession) -> list[DHEEvent]:
        raw = await self._get_text(self._poll_url(ctx.url_token, ctx.sid, ctx.websocket_sid))
        if not raw:
            return []
        if re.search(r"(^|[\ufffd\x1e])41(?:/1\.0\.0)?", raw):
            return [DHEEvent("__closed", None)]
        packets = self._decode_engineio_payload(raw)
        app_packets: list[str] = []
        for packet in packets:
            stripped = packet.strip("\x00\x1e\ufffd")
            if stripped == "1" or stripped == "41" or stripped.startswith("41/"):
                return [DHEEvent("__closed", None)]
            if stripped == "2":
                await self._post_packet(ctx, "3")
                continue
            if stripped == "3" or not stripped:
                continue
            app_packets.append(packet)
        return self._parse_socketio_events(app_packets)

    def _poll_url(self, token: str, sid: str | None, websocket_sid: str | None = None) -> str:
        token_q = quote(token or "", safe="")
        t = format(int(time.time() * 1000), "x")
        websocket_part = ""
        if websocket_sid:
            websocket_part = f"&websocketSid={quote(websocket_sid, safe='')}"
        if sid:
            return f"{self.base_url}/socket.io/?EIO=3&transport=polling&sid={quote(sid, safe='')}{websocket_part}&token={token_q}&t={t}"
        return f"{self.base_url}/socket.io/?EIO=3&transport=polling{websocket_part}&token={token_q}&t={t}"

    async def _get_text(self, url: str) -> str:
        timeout = aiohttp.ClientTimeout(total=70)
        async with self._session.get(url, timeout=timeout) as resp:
            body = await resp.read()
            if resp.status < 200 or resp.status >= 300:
                text = body.decode("utf-8", errors="replace")
                raise DHEError(f"GET {resp.status}: {text[:200]}")
            return body.decode("utf-8", errors="replace")

    async def _post_packet(self, ctx: DHESession, packet: str) -> str:
        body = f"{len(packet)}:{packet}"
        timeout = aiohttp.ClientTimeout(total=40)
        async with self._session.post(
            self._poll_url(ctx.url_token, ctx.sid, ctx.websocket_sid),
            data=body.encode("utf-8"),
            headers={"Content-Type": "text/plain;charset=UTF-8"},
            timeout=timeout,
        ) as resp:
            response_body = await resp.read()
            if resp.status < 200 or resp.status >= 300:
                text = response_body.decode("utf-8", errors="replace")
                raise DHEError(f"POST {resp.status}: {text[:200]}")
            return response_body.decode("utf-8", errors="replace")

    def _event_packet(self, event: str, data: Any) -> str:
        return f"42/{NS},{json.dumps([event, data], separators=(',', ':'))}"

    def _message_packet(self, payload: dict[str, Any]) -> str:
        message_id = self._next_socketio_message_id()
        return f"42/{NS},{message_id}{json.dumps(['message', payload], separators=(',', ':'))}"

    def _next_socketio_message_id(self) -> int:
        message_id = self._socketio_message_id
        self._socketio_message_id = 1 if message_id >= 999 else message_id + 1
        return message_id

    @staticmethod
    def _decode_engineio_payload(text: str) -> list[str]:
        if "\x1e" in text:
            return [part for part in text.split("\x1e") if part.strip()]
        if "\ufffd" in text:
            return [part for part in text.split("\ufffd") if part.strip()]
        packets: list[str] = []
        i = 0
        try:
            while i < len(text):
                if not text[i].isdigit():
                    if packets:
                        i += 1
                        continue
                    return [text]
                j = i
                while j < len(text) and text[j].isdigit():
                    j += 1
                if j >= len(text) or text[j] != ":":
                    return [text]
                length = int(text[i:j])
                start = j + 1
                end = start + length
                if end > len(text):
                    return [text]
                packets.append(text[start:end])
                i = end
            return packets or [text]
        except Exception:  # noqa: BLE001
            return [text]

    @staticmethod
    def _balanced_json_array(text: str, start_index: int) -> tuple[str | None, int]:
        start = text.find("[", start_index)
        if start < 0:
            return None, -1
        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
                continue
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return text[start : idx + 1], idx + 1
        return None, -1

    def _parse_socketio_events(self, packets: list[str]) -> list[DHEEvent]:
        out: list[DHEEvent] = []
        for raw_packet in packets:
            packet = raw_packet.strip("\x00\x1e\ufffd")
            if not packet:
                continue
            pos = 0
            while pos < len(packet):
                match = re.search(r"42(?:/1\.0\.0,)?\d*", packet[pos:])
                if not match:
                    break
                frame_start = pos + match.start()
                json_text, next_pos = self._balanced_json_array(packet, frame_start)
                if not json_text:
                    break
                try:
                    parsed = json.loads(json_text)
                    if isinstance(parsed, list) and parsed:
                        name = str(parsed[0])
                        data = parsed[1] if len(parsed) > 1 else None
                        out.append(DHEEvent(name, data))
                except json.JSONDecodeError:
                    _LOGGER.debug("Could not parse Socket.IO JSON frame: %s", json_text)
                pos = next_pos
        return out

    async def _load_token(self) -> str:
        if self._token:
            return self._token

        def _read() -> str:
            if not os.path.exists(self.token_path):
                return ""
            with open(self.token_path, "r", encoding="utf-8") as file:
                return file.read().strip()

        token = await self.hass.async_add_executor_job(_read)
        if token and (len(token) < 20 or any(ch.isspace() for ch in token)):
            _LOGGER.warning("Ignoring malformed stored DHE token at %s", self.token_path)
            token = ""
        self._token = token
        return self._token or ""

    async def _save_token(self, token: str) -> None:
        self._token = token

        def _write() -> None:
            token_dir = os.path.dirname(self.token_path)
            os.makedirs(token_dir, exist_ok=True)
            tmp_path = f"{self.token_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as file:
                file.write(token)
            try:
                os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
            os.replace(tmp_path, self.token_path)

        await self.hass.async_add_executor_job(_write)
