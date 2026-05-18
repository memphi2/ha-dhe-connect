"""Transport, authentication and token helpers for the DHE client."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import stat
import time
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import aiohttp

from .client_diagnostics import (
    diagnostic_error as _diagnostic_error,
    summarize_diagnostic_value as _summarize_diagnostic_value,
)
from .client_errors import (
    DHE_TRANSPORT_EXCEPTIONS as _DHE_TRANSPORT_EXCEPTIONS,
    runtime_transport_error_or_raise as _runtime_transport_error_or_raise,
)
from .client_types import (
    DEFAULT_ENGINEIO_PING_INTERVAL_SECONDS,
    DHEError,
    DHEEvent,
    DHESession,
    DHESessionClosed,
    ReconnectCallback,
)
from .engineio_helpers import (
    balanced_json_array as _balanced_json_array,
    decode_engineio_payload as _decode_engineio_payload,
    engineio_ping_interval as _engineio_ping_interval,
    parse_engineio_open_payload as _parse_engineio_open_payload,
)
from .pairing_helpers import pairing_result_success as _pairing_result_success
from .protocol import NS

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .client_reconnect_manager import DHEReconnectManager

WEBSOCKET_UPGRADE_TIMEOUT = 8.0
AUTH_POLL_TIMEOUT_SECONDS = 10.0


def _websocket_timeout(timeout: float) -> Any:
    timeout_cls = getattr(aiohttp, "ClientWSTimeout", None)
    if timeout_cls is None:
        return timeout
    return timeout_cls(ws_close=timeout)


class DHEClientTransportMixin:
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
        _reconnect_manager: DHEReconnectManager
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

    async def _open_authenticated_session(
        self,
        *,
        token_request_timeout_seconds: float = 120.0,
    ) -> DHESession:
        token = await self._load_token()
        if self._require_pairing_confirmation and token:
            _LOGGER.warning(
                "Pairing confirmation is required; ignoring existing token and "
                "requesting a fresh one."
            )
            token = ""
        if not token:
            _LOGGER.info("No stored DHE token. Requesting new token; confirm pairing on DHE if prompted.")
            self._pairing_active = True
            self._require_pairing_confirmation = True
            self._pairing_request_seen = False
            self._pairing_confirmed_success = False
            self._pairing_failed_explicit = False
            self._record_pairing_progress(
                "requesting_token",
                "No stored DHE token; requesting a new pairing token.",
                notify=True,
            )
            token = await self._request_initial_token(
                timeout_seconds=token_request_timeout_seconds,
            )
            if not token:
                raise DHEError("No token received. Pairing may be required on the DHE.")
        ctx = await self._open_session(token)
        try:
            await self._post_packet(ctx, self._event_packet("token_request", {"token": token, "name": self.name}))
            deadline = time.monotonic() + 120.0
            authenticated_received = False
            while time.monotonic() < deadline and not self._stopped.is_set():
                for event in await self._read_polling_events_once(ctx):
                    if event.name == "__closed":
                        raise DHESessionClosed("DHE closed Socket.IO session during authentication")
                    if event.name == "token_response" and isinstance(event.data, str) and len(event.data) > 20:
                        _LOGGER.debug(
                            "DHE auth event: token_response (pairing_active=%s, require_confirmation=%s, pairing_confirmed=%s)",
                            self._pairing_active,
                            self._require_pairing_confirmation,
                            self._pairing_confirmed_success,
                        )
                        token = event.data
                        await self._save_token(token)
                        if self._pairing_active:
                            self._record_pairing_progress(
                                "token_received",
                                "DHE pairing token received.",
                                notify=True,
                            )
                        await self._post_packet(ctx, self._event_packet("authenticate", {"token": token}))
                    elif event.name == "authenticated":
                        _LOGGER.debug(
                            "DHE auth event: authenticated (pairing_active=%s, require_confirmation=%s, pairing_confirmed=%s)",
                            self._pairing_active,
                            self._require_pairing_confirmation,
                            self._pairing_confirmed_success,
                        )
                        if self._pairing_failed_explicit:
                            raise DHEError("Pairing was rejected on the DHE")
                        if self._pairing_active:
                            if (
                                self._require_pairing_confirmation
                                and not self._pairing_confirmed_success
                            ):
                                authenticated_received = True
                                self._record_pairing_progress(
                                    "authenticated_pending_confirmation",
                                    "Authenticated, waiting for device pairing confirmation.",
                                    notify=True,
                                )
                                continue
                            if (
                                not self._require_pairing_confirmation
                                and not self._pairing_confirmed_success
                            ):
                                self._record_pairing_progress(
                                    "authenticated_without_device_confirmation",
                                    "DHE authentication completed without on-device pairing confirmation request.",
                                    notify=True,
                                )
                                self._pairing_active = False
                                self._pause_auto_reconnect_for_pairing = False
                                await self._upgrade_to_websocket(ctx)
                                return ctx
                            self._record_pairing_progress(
                                "authenticated",
                                "DHE pairing and authentication completed.",
                                notify=True,
                            )
                            self._pairing_active = False
                            self._require_pairing_confirmation = False
                            self._manual_pairing_requested = False
                            self._pause_auto_reconnect_for_pairing = False
                        await self._upgrade_to_websocket(ctx)
                        return ctx
                    elif event.name == "pairing_request":
                        _LOGGER.debug("DHE auth event: pairing_request")
                        self._record_pairing_requested()
                    elif event.name == "pairing_result":
                        _LOGGER.info("DHE auth event: pairing_result=%r", event.data)
                        self._record_pairing_result(event.data)
                if (
                    authenticated_received
                    and self._pairing_active
                    and self._require_pairing_confirmation
                    and self._pairing_confirmed_success
                ):
                    self._record_pairing_progress(
                        "authenticated",
                        "DHE pairing and authentication completed.",
                        notify=True,
                    )
                    self._pairing_active = False
                    self._require_pairing_confirmation = False
                    self._pause_auto_reconnect_for_pairing = False
                    await self._upgrade_to_websocket(ctx)
                    return ctx
                await asyncio.sleep(0.25)
            if authenticated_received and self._require_pairing_confirmation:
                raise DHEError(
                    "Authenticated, but DHE pairing confirmation was not completed in time"
                )
            raise DHEError("Auth timeout: no authenticated event received")
        except asyncio.CancelledError:
            await self._close_session(ctx)
            raise
        except _DHE_TRANSPORT_EXCEPTIONS as err:
            if self._pairing_active:
                self._record_pairing_failed(err)
            await self._close_session(ctx)
            raise
        except RuntimeError as err:
            transport_err = _runtime_transport_error_or_raise(err)
            if self._pairing_active:
                self._record_pairing_failed(transport_err)
            await self._close_session(ctx)
            raise

    async def _request_initial_token(self, *, timeout_seconds: float = 120.0) -> str:
        ctx = await self._open_session("")
        require_confirmation = self._require_pairing_confirmation
        pairing_confirmed = not require_confirmation
        saw_pairing_request = False
        candidate_token: str | None = None
        manual_auth_sent = False
        manual_websocket_attempted = False
        try:
            _LOGGER.debug(
                "DHE token request started (require_confirmation=%s).",
                require_confirmation,
            )
            await self._post_packet(ctx, self._event_packet("token_request", {"token": "", "name": self.name}))
            token_timeout = max(1.0, float(timeout_seconds))
            deadline = time.monotonic() + token_timeout
            while time.monotonic() < deadline and not self._stopped.is_set():
                try:
                    if ctx.websocket is not None:
                        events = await asyncio.wait_for(
                            self._read_events_once(ctx),
                            timeout=AUTH_POLL_TIMEOUT_SECONDS,
                        )
                    else:
                        events = await self._read_polling_events_once(ctx)
                except TimeoutError:
                    events = []
                for event in events:
                    if event.name == "__closed":
                        raise DHESessionClosed("DHE closed Socket.IO session while requesting token")
                    if event.name == "authenticated":
                        _LOGGER.debug(
                            "DHE event: authenticated while waiting for pairing_result "
                            "(pairing_confirmed=%s).",
                            pairing_confirmed,
                        )
                    if event.name == "pairing_request":
                        _LOGGER.debug("DHE event: pairing_request")
                        saw_pairing_request = True
                        self._record_pairing_requested()
                    if event.name == "pairing_result":
                        _LOGGER.info("DHE event: pairing_result=%r", event.data)
                        self._record_pairing_result(event.data)
                        if require_confirmation:
                            success = _pairing_result_success(event.data)
                            if success is False:
                                raise DHEError("Pairing confirmation rejected on DHE")
                            if success is True:
                                pairing_confirmed = True
                    if event.name == "token_response" and isinstance(event.data, str) and len(event.data) > 20:
                        _LOGGER.debug(
                            "DHE event: token_response (require_confirmation=%s, saw_pairing_request=%s, pairing_confirmed=%s)",
                            require_confirmation,
                            saw_pairing_request,
                            pairing_confirmed,
                        )
                        candidate_token = event.data
                        if not require_confirmation:
                            self._record_pairing_progress(
                                "token_received",
                                "DHE pairing token received.",
                                notify=True,
                            )
                            await self._save_token(candidate_token)
                            return candidate_token
                        if pairing_confirmed:
                            _LOGGER.debug(
                                "Token received after explicit pairing confirmation "
                                "(saw_pairing_request=%s).",
                                saw_pairing_request,
                            )
                            self._record_pairing_progress(
                                "token_received",
                                "DHE pairing token received.",
                                notify=True,
                            )
                            await self._save_token(candidate_token)
                            return candidate_token
                        if not saw_pairing_request:
                            if self._manual_pairing_requested:
                                if not manual_auth_sent:
                                    manual_auth_sent = True
                                    _LOGGER.info(
                                        "Manual pairing token received; authenticating "
                                        "same session while waiting for explicit pairing_result."
                                    )
                                    await self._post_packet(
                                        ctx,
                                        self._event_packet(
                                            "authenticate",
                                            {"token": candidate_token},
                                        ),
                                    )
                                if not manual_websocket_attempted:
                                    manual_websocket_attempted = True
                                    try:
                                        await self._upgrade_to_websocket(ctx)
                                        _LOGGER.debug(
                                            "Manual pairing session upgraded to websocket "
                                            "while waiting for pairing_result."
                                        )
                                    except _DHE_TRANSPORT_EXCEPTIONS as err:
                                        _LOGGER.debug(
                                            "Manual pairing websocket upgrade unavailable; "
                                            "continuing polling while waiting for pairing_result: %s",
                                            _diagnostic_error(err),
                                        )
                                    except RuntimeError as err:
                                        transport_err = _runtime_transport_error_or_raise(err)
                                        _LOGGER.debug(
                                            "Manual pairing websocket upgrade unavailable; "
                                            "continuing polling while waiting for pairing_result: %s",
                                            _diagnostic_error(transport_err),
                                        )
                                _LOGGER.debug(
                                    "Token received without pairing_request during manual pairing; "
                                    "waiting for explicit pairing_result from DHE."
                                )
                                continue
                            _LOGGER.debug(
                                "Token received without pairing_request; waiting for explicit pairing confirmation events."
                            )
                            continue
                        if not pairing_confirmed:
                            _LOGGER.debug(
                                "Token received, waiting for DHE pairing confirmation."
                            )
                            continue
                        await self._save_token(candidate_token)
                        return candidate_token
                    if (
                        require_confirmation
                        and candidate_token
                        and pairing_confirmed
                    ):
                        _LOGGER.debug(
                            "Pairing confirmed after token_response; proceeding "
                            "(saw_pairing_request=%s).",
                            saw_pairing_request,
                        )
                        self._record_pairing_progress(
                            "token_received",
                            "DHE pairing token received.",
                            notify=True,
                        )
                        await self._save_token(candidate_token)
                        return candidate_token
                await asyncio.sleep(0.3)
            if require_confirmation and candidate_token:
                raise DHEError("Token received but DHE pairing confirmation did not complete in time")
            raise DHEError("Token request timeout")
        except _DHE_TRANSPORT_EXCEPTIONS as err:
            self._record_pairing_failed(err)
            raise
        except RuntimeError as err:
            transport_err = _runtime_transport_error_or_raise(err)
            self._record_pairing_failed(transport_err)
            raise
        finally:
            await self._close_session(ctx)

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
        self._reconnect_manager.mark_connected()
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

    def _poll_url(self, token: str, sid: str | None, websocket_sid: str | None = None) -> str:
        token_q = quote(token or "", safe="")
        t = format(int(time.time() * 1000), "x")
        websocket_part = ""
        if websocket_sid:
            websocket_part = f"&websocketSid={quote(websocket_sid, safe='')}"
        if sid:
            return f"{self.base_url}/socket.io/?EIO=3&transport=polling&sid={quote(sid, safe='')}{websocket_part}&token={token_q}&t={t}"
        return f"{self.base_url}/socket.io/?EIO=3&transport=polling{websocket_part}&token={token_q}&t={t}"

    def _websocket_url_candidates(self, ctx: DHESession) -> tuple[tuple[str, str, str], ...]:
        websocket_sid = ctx.websocket_sid or ctx.sid
        candidates = [
            ("websocket-sid", websocket_sid, self._websocket_url(ctx.url_token, websocket_sid)),
        ]
        if ctx.websocket_sid:
            candidates.extend([
                ("polling-sid", ctx.sid, self._websocket_url(ctx.url_token, ctx.sid)),
            ])
        return tuple(candidates)

    def _websocket_url(self, token: str, sid: str) -> str:
        token_q = quote(token or "", safe="")
        sid_q = quote(sid, safe="")
        return f"ws://{self._url_host}:{self.port}/socket.io/?token={token_q}&EIO=3&transport=websocket&sid={sid_q}"

    def _websocket_headers(self, sid: str) -> dict[str, str]:
        return {
            "Cache-Control": "no-cache",
            "Cookie": f"io={sid}",
            "Origin": self.base_url,
            "Pragma": "no-cache",
        }

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

    @staticmethod
    def _websocket_message_packet(message: Any) -> str:
        if message.type == aiohttp.WSMsgType.TEXT:
            return str(message.data)
        if message.type == aiohttp.WSMsgType.BINARY:
            return bytes(message.data).decode("utf-8", errors="replace")
        return ""

    def _event_packet(self, event: str, data: Any) -> str:
        return f"42/{NS},{json.dumps([event, data], separators=(',', ':'))}"

    def _message_packet(self, payload: dict[str, Any]) -> str:
        message_id = self._next_socketio_message_id()
        return f"42/{NS},{message_id}{json.dumps(['message', payload], separators=(',', ':'))}"

    def _next_socketio_message_id(self) -> int:
        message_id = self._socketio_message_id
        self._socketio_message_id = 1 if message_id >= 999 else message_id + 1
        return message_id

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
                json_text, next_pos = _balanced_json_array(packet, frame_start)
                if not json_text:
                    break
                try:
                    parsed = json.loads(json_text)
                    if isinstance(parsed, list) and parsed:
                        name = str(parsed[0])
                        data = parsed[1] if len(parsed) > 1 else None
                        out.append(DHEEvent(name, data))
                except json.JSONDecodeError:
                    _LOGGER.debug(
                        "Could not parse Socket.IO JSON frame: %r",
                        _summarize_diagnostic_value(json_text),
                    )
                pos = next_pos
        return out

    async def _load_token(self) -> str:
        if self._token:
            return self._token

        def _read() -> str:
            if not os.path.exists(self.token_path):
                return ""
            with open(self.token_path, encoding="utf-8") as file:
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
            file_descriptor = os.open(
                tmp_path,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                stat.S_IRUSR | stat.S_IWUSR,
            )
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as file:
                file.write(token)
            with contextlib.suppress(OSError):
                os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(tmp_path, self.token_path)

        await self.hass.async_add_executor_job(_write)

    async def _clear_token(self) -> None:
        self._token = ""

        def _delete() -> None:
            with contextlib.suppress(FileNotFoundError):
                os.remove(self.token_path)

        await self.hass.async_add_executor_job(_delete)
