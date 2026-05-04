"""Persistent local Socket.IO/Engine.IO v3 client for Stiebel DHE Connect.

Design for this integration version:
- A single Engine.IO/Socket.IO long-polling session is kept open while Home Assistant runs.
- The client continuously long-polls the DHE and handles Engine.IO ping/pong frames.
- The setpoint is polled through ODB id 0 at the configured interval, default 600 seconds.
- Writes use the same open session whenever possible: ODB id 66 is written, then ODB id 0
  is requested as readback.
- If the DHE closes the session, the client marks the entity unavailable and reconnects.
"""

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
ID_SETPOINT = 0
ID_SET_REQ = 66

SetpointCallback = Callable[[float], None]
AvailabilityCallback = Callable[[bool], None]


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


def _round_to_half_c(value: float) -> float:
    return round(value * 2.0) / 2.0


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _c_to_raw_tenths(value: float) -> int:
    return int(round(value * 10.0))


def _raw_tenths_to_c(value: int | float) -> float:
    return float(value) / 10.0


def _build_req66(temp_c: float, addr: int) -> int:
    raw = _c_to_raw_tenths(temp_c) & 1023
    return int(raw | ((addr & 0xFF) << 10))


class DHEClient:
    """Persistent Engine.IO v3 long-polling client for DHE Connect."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        token_file: str,
        name: str,
    ) -> None:
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

        self._poll_interval = 600
        self._setpoint_callback: SetpointCallback | None = None
        self._availability_callback: AvailabilityCallback | None = None
        self._available = False
        self._last_setpoint: float | None = None
        self._pending_setpoint_future: asyncio.Future[float] | None = None
        self._pending_expected_setpoint: float | None = None
        self._last_setpoint_request = 0.0

    @property
    def last_setpoint(self) -> float | None:
        """Return the last known setpoint."""
        return self._last_setpoint

    @property
    def available(self) -> bool:
        """Return current connection availability."""
        return self._available

    async def start(
        self,
        poll_interval: int,
        setpoint_callback: SetpointCallback,
        availability_callback: AvailabilityCallback,
    ) -> None:
        """Start persistent DHE session and polling loop."""
        self._poll_interval = max(60, int(poll_interval))
        self._setpoint_callback = setpoint_callback
        self._availability_callback = availability_callback

        if self._runner and not self._runner.done():
            return

        self._stopped.clear()

        # Important for Home Assistant startup:
        # this is a long-running Engine.IO long-poll loop and must be scheduled as a
        # background task. Using hass.async_create_task during setup can make HA keep
        # showing "Home Assistant is starting" because the task is considered part
        # of startup work.
        create_background_task = getattr(self.hass, "async_create_background_task", None)
        if create_background_task is not None:
            self._runner = create_background_task(
                self._run_loop(),
                "stiebel_dhe_connect_poll_loop",
            )
        else:
            self._runner = self.hass.async_create_task(
                self._run_loop(),
                name="stiebel_dhe_connect_poll_loop",
            )

    async def stop(self) -> None:
        """Stop persistent polling loop and close the DHE namespace session."""
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
        self._set_available(False)

    async def request_setpoint_poll(self) -> None:
        """Request setpoint on the persistent session."""
        ctx = self._ctx
        if ctx is None:
            raise DHEError("DHE session is not connected")
        await self._request_setpoint(ctx)

    async def set_temperature(self, temperature: float) -> float:
        """Set setpoint via ODB id 66 and verify by reading ODB id 0 on the open session."""
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

                    _LOGGER.debug(
                        "Setting DHE setpoint to %.1f °C via ODB id 66, addr=%s, raw=%s",
                        requested,
                        addr,
                        req_value,
                    )

                    future = self._new_setpoint_future(requested)

                    await self._post_packet(ctx, self._message_packet({
                        "command": "assign:ste.common.odb:value",
                        "value": {"id": ID_SET_REQ, "value": req_value},
                    }))
                    await self._request_setpoint(ctx)

                    readback = await asyncio.wait_for(future, timeout=12)
                    if abs(readback - requested) < 0.01:
                        return readback

                    raise DHEError(f"readback was {readback:.1f} °C, expected {requested:.1f} °C")
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("Could not set DHE setpoint on attempt %s/2: %s", attempt + 1, err)
                    self._clear_pending_future(err)
                    if attempt == 0:
                        await self._force_reconnect()
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not set DHE setpoint: {err}") from err

        raise DHEError("Could not set DHE setpoint")

    async def _run_loop(self) -> None:
        """Persistent reconnecting Engine.IO long-poll loop."""
        while not self._stopped.is_set():
            try:
                self._ctx = await self._open_authenticated_session()
                self._ready.set()
                self._set_available(True)
                self._last_setpoint_request = 0.0
                await self._request_setpoint(self._ctx)

                while not self._stopped.is_set() and self._ctx is not None:
                    now = time.monotonic()
                    if now - self._last_setpoint_request >= self._poll_interval:
                        await self._request_setpoint(self._ctx)

                    events = await self._read_events_once(self._ctx)
                    for event in events:
                        await self._handle_runtime_event(event)

            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("DHE persistent session failed: %s", err)
                self._clear_pending_future(err)
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
        """Open an authenticated persistent Socket.IO session."""
        token = await self._load_token()

        if not token:
            _LOGGER.info("No stored DHE token. Requesting new token; confirm pairing on DHE if prompted.")
            token = await self._request_initial_token()
            if not token:
                raise DHEError("No token received. Pairing may be required on the DHE.")

        ctx = await self._open_session(token)
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
                    _LOGGER.debug("DHE authenticated")
                    return ctx

                elif event.name == "pairing_request":
                    _LOGGER.info("DHE pairing requested. Confirm on the DHE if prompted.")

                elif event.name == "pairing_result":
                    # Some devices return result=false,response=true with a valid authenticated session.
                    _LOGGER.debug("DHE pairing_result received: %s", event.data)

            if time.monotonic() - last_nudge > 0.9:
                await self._post_packet(ctx, self._event_packet("token_request", {"token": token, "name": self.name}))
                last_nudge = time.monotonic()

            await asyncio.sleep(0.25)

        raise DHEError("Auth timeout: no authenticated event received")

    async def _request_initial_token(self) -> str:
        """Open a blank-token session and request a token."""
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
        open_payload = await self._get_text(self._poll_url(token_for_url, None))
        sid_match = re.search(r'"sid":"([^"]+)"', open_payload)

        if not sid_match:
            raise DHEError(f"Could not extract sid from open payload: {open_payload!r}")

        ctx = DHESession(sid=sid_match.group(1), url_token=token_for_url)

        await self._post_packet(ctx, "40")
        await self._post_packet(ctx, f"40/{NS},")

        return ctx

    async def _close_session(self, ctx: DHESession) -> None:
        """Best-effort namespace close."""
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
        value = data.get("value")
        if not (
            data.get("command") == "set:ste.common.odb:value"
            and isinstance(value, dict)
            and int(value.get("id", -1)) == ID_SETPOINT
        ):
            return

        raw = int(value.get("value"))
        setpoint = _raw_tenths_to_c(raw)
        self._handle_setpoint(setpoint)

    def _handle_setpoint(self, value: float) -> None:
        self._last_setpoint = value
        if self._setpoint_callback:
            self._setpoint_callback(value)
        future = self._pending_setpoint_future
        expected = self._pending_expected_setpoint
        if future is not None and not future.done():
            if expected is None or abs(value - expected) < 0.01:
                future.set_result(value)
                self._pending_setpoint_future = None
                self._pending_expected_setpoint = None

    async def _request_setpoint(self, ctx: DHESession) -> None:
        """Request ODB id 0 setpoint on the persistent session."""
        self._last_setpoint_request = time.monotonic()
        await self._post_packet(ctx, self._message_packet({
            "command": "get:ste.common.odb:value",
            "value": {"id": ID_SETPOINT, "value": ""},
        }))

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

    def _set_available(self, available: bool) -> None:
        if self._available == available:
            return
        self._available = available
        if self._availability_callback:
            self._availability_callback(available)

    async def _read_events_once(self, ctx: DHESession) -> list[DHEEvent]:
        raw = await self._get_text(self._poll_url(ctx.url_token, ctx.sid))

        if not raw:
            return []

        if re.search(r"(^|[\ufffd\x1e])41(?:/1\.0\.0)?", raw):
            return [DHEEvent("__closed", None)]

        packets = self._decode_engineio_payload(raw)
        app_packets: list[str] = []
        for packet in packets:
            stripped = packet.strip("\x00\x1e\ufffd")
            if stripped == "2":
                # Engine.IO ping. The client must pong to keep long-polling sessions alive.
                await self._post_packet(ctx, "3")
                continue
            if stripped == "3" or not stripped:
                continue
            app_packets.append(packet)

        return self._parse_socketio_events(app_packets)

    def _poll_url(self, token: str, sid: str | None) -> str:
        token_q = quote(token or "", safe="")
        t = format(int(time.time() * 1000), "x")

        if sid:
            return (
                f"{self.base_url}/socket.io/?EIO=3&transport=polling"
                f"&sid={quote(sid, safe='')}&token={token_q}&t={t}"
            )

        return f"{self.base_url}/socket.io/?EIO=3&transport=polling&token={token_q}&t={t}"

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
            self._poll_url(ctx.url_token, ctx.sid),
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
        return self._event_packet("message", payload)

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
                # Some filesystems used by Home Assistant containers may not support chmod.
                pass
            os.replace(tmp_path, self.token_path)

        await self.hass.async_add_executor_job(_write)
