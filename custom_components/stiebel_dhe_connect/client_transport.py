"""Transport, authentication and token helpers for the DHE client."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

import aiohttp

from .client_constants import AUTH_POLL_TIMEOUT_SECONDS
from .client_diagnostics import diagnostic_error as _diagnostic_error
from .client_errors import (
    DHE_TRANSPORT_EXCEPTIONS as _DHE_TRANSPORT_EXCEPTIONS,
    runtime_transport_error_or_raise as _runtime_transport_error_or_raise,
)
from .client_transport_auth import DHEClientTransportAuthMixin
from .client_transport_helpers import DHEClientTransportHelpersMixin
from .client_types import (
    DEFAULT_ENGINEIO_PING_INTERVAL_SECONDS,
    DHEError,
    DHEEvent,
    DHESession,
    DHESessionClosed,
    ReconnectCallback,
)
from .engineio_helpers import (
    decode_engineio_payload as _decode_engineio_payload,
    engineio_ping_interval as _engineio_ping_interval,
    parse_engineio_open_payload as _parse_engineio_open_payload,
)
from .protocol import NS

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .client_connection_supervisor import DHEConnectionSupervisor

WEBSOCKET_UPGRADE_TIMEOUT = 8.0


def _websocket_timeout(timeout: float) -> Any:
    timeout_cls = getattr(aiohttp, "ClientWSTimeout", None)
    if timeout_cls is None:
        return timeout
    return timeout_cls(ws_close=timeout)


class DHEClientTransportMixin(
    DHEClientTransportAuthMixin,
    DHEClientTransportHelpersMixin,
):
    """Transport, authentication and token persistence methods for DHEClient."""

    if TYPE_CHECKING:
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
        _reconnect_grace_task: asyncio.Task[None] | None
        _connection_supervisor: DHEConnectionSupervisor
        _reconnect_callbacks: set[ReconnectCallback]
        _reconnect_count: int
        _require_pairing_confirmation: bool
        _send_lock: asyncio.Lock
        _session: aiohttp.ClientSession
        _socketio_message_id: int
        _stopped: asyncio.Event
        _token: str | None
        _url_host: str

        def _record_pairing_progress(
            self,
            state: str,
            message: str,
            *,
            notify: bool = False,
            result: Any | None = None,
        ) -> None: ...

        def _record_pairing_requested(self) -> None: ...

        def _record_pairing_result(self, result: Any) -> None: ...

        def _record_pairing_failed(self, error: BaseException) -> None: ...

        def _set_online(self, online: bool) -> None: ...

        def _set_available(
            self,
            available: bool,
            *,
            immediate: bool = False,
        ) -> None: ...

        def _mark_reconnecting(
            self,
            reason: str,
            *,
            immediate_availability: bool = False,
        ) -> float: ...

        def _cancel_reconnect_grace_timer(self) -> None: ...

        def _update_diagnostics(self, **updates: Any) -> None: ...

        def _notify_callbacks(
            self,
            callback_name: str,
            callbacks: set[Callable[..., None]],
            *args: Any,
        ) -> None: ...

        def _create_background_task(
            self,
            coro: Coroutine[Any, Any, Any],
            name: str,
        ) -> asyncio.Task[Any]: ...

    async def _open_session(self, token_for_url: str) -> DHESession:
        open_payload = await self._get_text(self._poll_url(token_for_url, None, None))
        try:
            open_data = _parse_engineio_open_payload(open_payload)
        except ValueError as err:
            raise DHEError(str(err)) from err
        sid = str(open_data.get("sid", "")).strip()
        if not sid:
            raise DHEError(f"Could not extract sid from open payload: {open_payload!r}")
        websocket_sid = open_data.get("websocketSid")
        websocket_sid = str(websocket_sid).strip() if websocket_sid is not None else None
        ctx = DHESession(
            sid=sid,
            url_token=token_for_url,
            websocket_sid=websocket_sid or None,
            ping_interval=_engineio_ping_interval(
                open_data,
                default_interval=DEFAULT_ENGINEIO_PING_INTERVAL_SECONDS,
            ),
        )
        await self._post_packet(ctx, f"40/{NS}")
        return ctx

    async def _close_session(self, ctx: DHESession) -> None:
        ping_task = ctx.websocket_ping_task
        ctx.websocket_ping_task = None
        if (
            ping_task is not None
            and ping_task is not asyncio.current_task()
            and not ping_task.done()
        ):
            ping_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ping_task
        with contextlib.suppress(Exception):  # noqa: BLE001
            await self._post_packet(ctx, f"41/{NS}")
        websocket = ctx.websocket
        ctx.websocket = None
        if websocket is not None and not websocket.closed:
            await websocket.close()

    async def _force_reconnect(
        self,
        ctx: DHESession | None = None,
        *,
        immediate_availability: bool = False,
        reason: str | None = None,
    ) -> None:
        if ctx is not None and self._ctx is not ctx:
            await self._close_session(ctx)
            return

        ctx = self._ctx
        self._ctx = None
        self._ready.clear()
        self._mark_reconnecting(
            reason or "Forced reconnect requested",
            immediate_availability=immediate_availability,
        )
        if ctx is not None:
            await self._close_session(ctx)

    async def _ensure_ready(self, timeout: float) -> None:
        if self._ctx is not None and self._available:
            return
        await asyncio.wait_for(self._ready.wait(), timeout=timeout)

    def _record_session_connected(self) -> None:
        self._connection_supervisor.mark_connected()
        self._pairing_retry_attempts = 0
        self._pause_auto_reconnect_for_pairing = False
        if not self._has_connected:
            self._has_connected = True
            return

        self._reconnect_count += 1
        self._notify_callbacks(
            "reconnect",
            self._reconnect_callbacks,
            self._reconnect_count,
        )

    async def _upgrade_to_websocket(self, ctx: DHESession) -> None:
        websocket = None
        try:
            errors: list[str] = []
            for label, sid, url in self._websocket_url_candidates(ctx):
                websocket = None
                try:
                    websocket = await self._session.ws_connect(
                        url,
                        autoping=True,
                        heartbeat=None,
                        headers=self._websocket_headers(sid),
                        timeout=_websocket_timeout(WEBSOCKET_UPGRADE_TIMEOUT),
                    )
                    await websocket.send_str("2probe")
                    deadline = time.monotonic() + WEBSOCKET_UPGRADE_TIMEOUT
                    while time.monotonic() < deadline:
                        timeout = max(0.1, deadline - time.monotonic())
                        message = await asyncio.wait_for(websocket.receive(), timeout=timeout)
                        packet = self._websocket_message_packet(message)
                        if packet == "3probe":
                            async with self._send_lock:
                                await websocket.send_str("5")
                            ctx.websocket = websocket
                            ctx.websocket_ping_task = self._create_background_task(
                                self._websocket_ping_loop(ctx),
                                "stiebel_dhe_connect_websocket_ping",
                            )
                            return
                        if packet == "2":
                            await websocket.send_str("3")
                            continue
                        if message.type in {
                            aiohttp.WSMsgType.CLOSE,
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.CLOSING,
                            aiohttp.WSMsgType.ERROR,
                        }:
                            break
                        if packet == "3" or not packet:
                            continue
                        _LOGGER.debug("Ignoring unexpected DHE websocket probe packet: %r", packet)
                    raise DHEError("probe timeout")
                except _DHE_TRANSPORT_EXCEPTIONS as err:
                    errors.append(f"{label}: {type(err).__name__}")
                    if websocket is not None and not websocket.closed:
                        await websocket.close()
                except RuntimeError as err:
                    transport_err = _runtime_transport_error_or_raise(err)
                    errors.append(f"{label}: {type(transport_err).__name__}")
                    if websocket is not None and not websocket.closed:
                        await websocket.close()
            raise DHEError("; ".join(errors) or "probe timeout")
        except _DHE_TRANSPORT_EXCEPTIONS as err:
            if websocket is not None and not websocket.closed:
                await websocket.close()
            raise DHEError(f"DHE websocket upgrade failed: {err}") from err
        except RuntimeError as err:
            transport_err = _runtime_transport_error_or_raise(err)
            if websocket is not None and not websocket.closed:
                await websocket.close()
            raise DHEError(f"DHE websocket upgrade failed: {transport_err}") from err

    async def _websocket_ping_loop(self, ctx: DHESession) -> None:
        try:
            while not self._stopped.is_set() and ctx.websocket is not None and not ctx.websocket.closed:
                await asyncio.sleep(ctx.ping_interval)
                if self._stopped.is_set() or ctx.websocket is None or ctx.websocket.closed:
                    return
                await self._send_websocket_packet(ctx, "2")
        except asyncio.CancelledError:
            return
        except _DHE_TRANSPORT_EXCEPTIONS as err:
            if not self._stopped.is_set():
                await self._force_reconnect(
                    ctx,
                    reason=f"Heartbeat failed: {_diagnostic_error(err)}",
                )
        except RuntimeError as err:
            transport_err = _runtime_transport_error_or_raise(err)
            if not self._stopped.is_set():
                await self._force_reconnect(
                    ctx,
                    reason=f"Heartbeat failed: {_diagnostic_error(transport_err)}",
                )

    async def _read_events_once(self, ctx: DHESession) -> list[DHEEvent]:
        if ctx.websocket is None:
            raise DHESessionClosed("DHE websocket transport is not connected")
        return await self._read_websocket_events_once(ctx)

    async def _read_polling_events_once(self, ctx: DHESession) -> list[DHEEvent]:
        try:
            raw = await self._get_text(
                self._poll_url(ctx.url_token, ctx.sid, ctx.websocket_sid),
                timeout=AUTH_POLL_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            return []
        if not raw:
            return []
        if re.search(r"(^|[\ufffd\x1e])41(?:/1\.0\.0)?", raw):
            return [DHEEvent("__closed", None)]
        packets = _decode_engineio_payload(raw)
        app_packets: list[str] = []
        for packet in packets:
            stripped = packet.strip("\x00\x1e\ufffd")
            if stripped in {"1", "41"} or stripped.startswith("41/"):
                return [DHEEvent("__closed", None)]
            if stripped == "2":
                await self._post_packet(ctx, "3")
                continue
            if stripped == "3" or not stripped:
                continue
            app_packets.append(packet)
        return self._parse_socketio_events(app_packets)

    async def _read_websocket_events_once(self, ctx: DHESession) -> list[DHEEvent]:
        websocket = ctx.websocket
        if websocket is None:
            return []
        message = await websocket.receive()
        if message.type in {
            aiohttp.WSMsgType.CLOSE,
            aiohttp.WSMsgType.CLOSED,
            aiohttp.WSMsgType.CLOSING,
            aiohttp.WSMsgType.ERROR,
        }:
            return [DHEEvent("__closed", None)]
        raw = self._websocket_message_packet(message)
        if not raw:
            return []

        packets = _decode_engineio_payload(raw)
        app_packets: list[str] = []
        for packet in packets:
            stripped = packet.strip("\x00\x1e\ufffd")
            if stripped in {"1", "41"} or stripped.startswith("41/"):
                return [DHEEvent("__closed", None)]
            if stripped == "2":
                await self._send_websocket_packet(ctx, "3")
                continue
            if stripped == "3" or not stripped:
                continue
            app_packets.append(packet)
        return self._parse_socketio_events(app_packets)

    async def _get_text(self, url: str, *, timeout: float = 70.0) -> str:
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        async with self._session.get(url, timeout=client_timeout) as resp:
            body = await resp.read()
            if resp.status < 200 or resp.status >= 300:
                text = body.decode("utf-8", errors="replace")
                raise DHEError(f"GET {resp.status}: {text[:200]}")
            return body.decode("utf-8", errors="replace")

    async def _post_packet(self, ctx: DHESession, packet: str) -> str:
        if ctx.websocket is not None:
            await self._send_websocket_packet(ctx, packet)
            return ""

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

    async def _send_websocket_packet(self, ctx: DHESession, packet: str) -> None:
        websocket = ctx.websocket
        if websocket is None or websocket.closed:
            raise DHESessionClosed("DHE websocket transport is closed")
        async with self._send_lock:
            await websocket.send_str(packet)
