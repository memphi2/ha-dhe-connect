"""Transport tests backed by a lightweight fake DHE Engine.IO server."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import functools
import json
from pathlib import Path
import sys
import tempfile
from typing import Any
import unittest
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
from aiohttp import web

try:
    from tests.test_client_weather_favorites import (
        _load_client,
        _load_component_module,
        _load_protocol,
    )
except ModuleNotFoundError:
    from test_client_weather_favorites import (
        _load_client,
        _load_component_module,
        _load_protocol,
    )


STORED_TOKEN = "stored-token-fixture-000001"
PAIRING_TOKEN = "pairing-token-fixture-0001"
PACKAGE_NAME = "custom_components.stiebel_dhe_connect"


def _decode_length_prefixed_packets(body: str) -> list[str]:
    packets: list[str] = []
    pos = 0
    while pos < len(body):
        colon = body.find(":", pos)
        if colon < 0:
            packets.append(body[pos:])
            break
        try:
            length = int(body[pos:colon])
        except ValueError:
            packets.append(body[pos:])
            break
        start = colon + 1
        end = start + length
        packets.append(body[start:end])
        pos = end
    return packets


def _extract_assign_value(packet: str) -> int | str:
    _, payload = packet.split(",", 1)
    decode_offset = 0
    while decode_offset < len(payload) and payload[decode_offset].isdigit():
        decode_offset += 1
    if decode_offset and decode_offset < len(payload):
        payload = payload[decode_offset:]
    data = json.loads(payload)
    value_data = data[1]["value"]
    return value_data["value"] if isinstance(value_data, dict) else value_data


class FakeDHEEngineIOServer:
    """Minimal Engine.IO v3 server for transport-level client tests."""

    def __init__(self, namespace: str, *, websocket_enabled: bool = True) -> None:
        self.namespace = namespace
        self.websocket_enabled = websocket_enabled
        self.host = "127.0.0.1"
        self.port = 0
        self.polling_sid = "polling-sid"
        self.websocket_sid = "websocket-sid"
        self.posted_packets: list[str] = []
        self.websocket_packets: list[str] = []
        self.websockets: list[web.WebSocketResponse] = []
        self._poll_packets: asyncio.Queue[str] = asyncio.Queue()
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self.websocket_upgraded: asyncio.Event | None = None
        self.packet_posted: asyncio.Event | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    async def __aenter__(self) -> FakeDHEEngineIOServer:
        self.websocket_upgraded = asyncio.Event()
        self.packet_posted = asyncio.Event()
        app = web.Application()
        app.router.add_get("/socket.io/", self._handle_get)
        app.router.add_post("/socket.io/", self._handle_post)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, 0)
        await self._site.start()
        sockets = self._site._server.sockets if self._site._server is not None else []
        self.port = int(sockets[0].getsockname()[1])
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: Any,
    ) -> None:
        if self._runner is not None:
            await self._runner.cleanup()

    def queue_event(self, event: str, data: Any) -> None:
        payload = json.dumps([event, data], separators=(",", ":"))
        self.queue_packet(f"42/{self.namespace},{payload}")

    def queue_packet(self, packet: str) -> None:
        self._poll_packets.put_nowait(packet)

    def queue_authentication(self) -> None:
        self.queue_event("authenticated", {"ok": True})

    def queue_pairing_request(self) -> None:
        self.queue_event("pairing_request", {"requested": True})

    def queue_pairing_result(self, accepted: bool) -> None:
        self.queue_event(
            "pairing_result",
            {"result": "accepted" if accepted else "rejected"},
        )

    def queue_token_response(self, token: str) -> None:
        self.queue_event("token_response", token)

    def queue_device_info(self) -> None:
        self.queue_event(
            "message",
            {
                "command": "set:ste.common.version:gadgetData",
                "value": {
                    "type": "DHE Connect 18/21/24",
                    "id": "fixture-device",
                    "wlan": "AA-BB-CC-DD-EE-FF",
                    "bluetooth": "11-22-33-44-55-66",
                },
            },
        )

    def queue_socket_close(self) -> None:
        self.queue_packet(f"41/{self.namespace}")

    async def close_active_websockets(self) -> None:
        """Close all currently active fake-DHE websocket transports."""
        for websocket in list(self.websockets):
            if not websocket.closed:
                await websocket.close()

    async def wait_for_posted_packet(
        self,
        needle: str,
        *,
        timeout: float = 1.0,
    ) -> str:
        """Wait until a posted Socket.IO packet contains the expected text."""
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            for packet in self.posted_packets:
                if needle in packet:
                    return packet
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise AssertionError(
                    f"Timed out waiting for posted packet containing {needle!r}; "
                    f"packets={self.posted_packets!r}"
                )
            if self.packet_posted is None:
                await asyncio.sleep(min(0.01, remaining))
                continue
            try:
                await asyncio.wait_for(self.packet_posted.wait(), timeout=remaining)
            except TimeoutError as err:
                raise AssertionError(
                    f"Timed out waiting for posted packet containing {needle!r}; "
                    f"packets={self.posted_packets!r}"
                ) from err
            self.packet_posted.clear()

    async def wait_for_posted_packet_count(
        self,
        needle: str,
        count: int,
        *,
        timeout: float = 1.0,
    ) -> list[str]:
        """Wait until at least count posted Socket.IO packets contain the text."""
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            matches = [packet for packet in self.posted_packets if needle in packet]
            if len(matches) >= count:
                return matches
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise AssertionError(
                    f"Timed out waiting for {count} posted packets containing "
                    f"{needle!r}; packets={self.posted_packets!r}"
                )
            if self.packet_posted is None:
                await asyncio.sleep(min(0.01, remaining))
                continue
            try:
                await asyncio.wait_for(self.packet_posted.wait(), timeout=remaining)
            except TimeoutError as err:
                raise AssertionError(
                    f"Timed out waiting for {count} posted packets containing "
                    f"{needle!r}; packets={self.posted_packets!r}"
                ) from err
            self.packet_posted.clear()

    async def _handle_get(self, request: web.Request) -> web.StreamResponse:
        if request.query.get("transport") == "websocket":
            return await self._handle_websocket(request)
        if not request.query.get("sid"):
            return web.Response(
                text=(
                    "0"
                    + json.dumps(
                        {
                            "sid": self.polling_sid,
                            "websocketSid": self.websocket_sid,
                            "pingInterval": 10_000,
                        },
                        separators=(",", ":"),
                    )
                ),
                content_type="text/plain",
            )
        try:
            packet = self._poll_packets.get_nowait()
        except asyncio.QueueEmpty:
            packet = ""
        return web.Response(text=packet, content_type="text/plain")

    async def _handle_post(self, request: web.Request) -> web.Response:
        body = await request.text()
        self.posted_packets.extend(_decode_length_prefixed_packets(body))
        if self.packet_posted is not None:
            self.packet_posted.set()
        return web.Response(text="ok", content_type="text/plain")

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        if not self.websocket_enabled:
            raise web.HTTPServiceUnavailable(text="websocket disabled")
        websocket = web.WebSocketResponse(autoping=True)
        await websocket.prepare(request)
        self.websockets.append(websocket)
        async for message in websocket:
            if message.type != aiohttp.WSMsgType.TEXT:
                continue
            packet = str(message.data)
            self.websocket_packets.append(packet)
            if packet == "2probe":
                await websocket.send_str("3probe")
            elif packet == "5" and self.websocket_upgraded is not None:
                self.websocket_upgraded.set()
            elif packet == "2":
                await websocket.send_str("3")
            else:
                await self._send_queued_websocket_packets(websocket)
        return websocket

    async def _send_queued_websocket_packets(
        self,
        websocket: web.WebSocketResponse,
    ) -> None:
        while True:
            try:
                packet = self._poll_packets.get_nowait()
            except asyncio.QueueEmpty:
                return
            await websocket.send_str(packet)


class _ClosedWebSocket:
    """Minimal closed websocket object for command-retry tests."""

    closed = True

    async def close(self) -> None:
        return None


class _TransportClosingWebSocket:
    """Minimal websocket that raises a transport shutdown error during close."""

    closed = False

    async def close(self) -> None:
        raise RuntimeError("websocket connection is closed")


class _ProgrammingErrorClosingWebSocket:
    """Minimal websocket that raises a programming error during close."""

    closed = False

    async def close(self) -> None:
        raise RuntimeError("programming error")


@asynccontextmanager
async def _connected_fake_client(
    client_module: Any,
    server: FakeDHEEngineIOServer,
) -> AsyncIterator[tuple[Any, Any, Any]]:
    """Create a ready DHEClient connected to the fake Engine.IO server."""
    DHEClient = client_module.DHEClient
    async with aiohttp.ClientSession() as session:
        client_module.async_get_clientsession = Mock(return_value=session)
        client = DHEClient(
            _FakeHass(asyncio.get_running_loop()),
            server.host,
            server.port,
            ".storage/test-token",
            "DHE",
        )
        ctx = await DHEClient._open_session(client, "stored-token")
        client._ctx = ctx
        client._ready.set()
        client._available = True
        try:
            yield DHEClient, client, ctx
        finally:
            await DHEClient._close_session(client, ctx)


async def _queue_message_and_handle(
    server: FakeDHEEngineIOServer,
    client: Any,
    ctx: Any,
    command: str,
    value: Any,
) -> None:
    """Queue one fake DHE message and let the client consume it."""
    server.queue_event("message", {"command": command, "value": value})
    await _handle_next_polling_event(client, ctx)


def _mock_pairing_notifications() -> None:
    pairing_module = sys.modules[f"{PACKAGE_NAME}.client_pairing"]
    pairing_module.persistent_notification.async_create = Mock()
    pairing_module.persistent_notification.async_dismiss = Mock()


class TestFakeDHEEngineIOServer(unittest.IsolatedAsyncioTestCase):
    """Exercise real HTTP/WebSocket transport against the fake DHE server."""

    def test_websocket_timeout_uses_close_timeout_only(self) -> None:
        transport_module = _load_component_module("client_transport")

        timeout = transport_module._websocket_timeout(8.0)

        if hasattr(timeout, "ws_receive"):
            self.assertIsNone(timeout.ws_receive)
            self.assertEqual(timeout.ws_close, 8.0)
        else:
            self.assertEqual(timeout, 8.0)

    def test_websocket_receive_timeout_scales_with_ping_interval(self) -> None:
        transport_module = _load_component_module("client_transport")
        client_types_module = _load_component_module("client_types")
        ctx = client_types_module.DHESession(
            url_token="token",
            sid="sid",
            ping_interval=30.0,
        )

        self.assertEqual(transport_module._websocket_receive_timeout(ctx), 54.0)

    async def test_close_session_suppresses_websocket_transport_shutdown(self) -> None:
        client_module = _load_client()
        client_types_module = _load_component_module("client_types")
        DHEClient = client_module.DHEClient
        client = DHEClient.__new__(DHEClient)
        client._post_packet = AsyncMock()
        ctx = client_types_module.DHESession(
            url_token="token",
            sid="sid",
            websocket=_TransportClosingWebSocket(),
        )

        await DHEClient._close_session(client, ctx)

        self.assertIsNone(ctx.websocket)
        client._post_packet.assert_awaited_once()

    async def test_close_session_keeps_programming_runtime_errors_visible(self) -> None:
        client_module = _load_client()
        client_types_module = _load_component_module("client_types")
        DHEClient = client_module.DHEClient
        client = DHEClient.__new__(DHEClient)
        client._post_packet = AsyncMock()
        ctx = client_types_module.DHESession(
            url_token="token",
            sid="sid",
            websocket=_ProgrammingErrorClosingWebSocket(),
        )

        with self.assertRaisesRegex(RuntimeError, "programming error"):
            await DHEClient._close_session(client, ctx)

    async def test_client_polling_session_reads_fake_dhe_events(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        async with (
            FakeDHEEngineIOServer(protocol_module.NS) as server,
            aiohttp.ClientSession() as session,
        ):
                client = DHEClient.__new__(DHEClient)
                client._session = session
                client.base_url = server.base_url
                client._url_host = server.host
                client.port = server.port

                ctx = await DHEClient._open_session(client, "stored-token")
                server.queue_event("message", {"command": "getActors", "value": [1]})

                events = await DHEClient._read_polling_events_once(client, ctx)

        self.assertEqual(ctx.sid, server.polling_sid)
        self.assertEqual(ctx.websocket_sid, server.websocket_sid)
        self.assertIn(f"40/{protocol_module.NS}", server.posted_packets)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].name, "message")
        self.assertEqual(events[0].data, {"command": "getActors", "value": [1]})

    async def test_client_websocket_upgrade_uses_fake_dhe_probe(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient
        DHESession = client_module.DHESession

        async with (
            FakeDHEEngineIOServer(protocol_module.NS) as server,
            aiohttp.ClientSession() as session,
        ):
                client = DHEClient.__new__(DHEClient)
                client._session = session
                client.base_url = server.base_url
                client._url_host = server.host
                client.port = server.port
                client._send_lock = asyncio.Lock()
                client._stopped = asyncio.Event()

                def _capture_background_task(
                    coro: Any,
                    _name: str,
                ) -> asyncio.Task[None]:
                    return asyncio.create_task(coro)

                client._create_background_task = Mock(side_effect=_capture_background_task)
                ctx = DHESession(
                    sid=server.polling_sid,
                    url_token="stored-token",
                    websocket_sid=server.websocket_sid,
                )

                await DHEClient._upgrade_to_websocket(client, ctx)
                if server.websocket_upgraded is not None:
                    await asyncio.wait_for(server.websocket_upgraded.wait(), timeout=1)
                await DHEClient._close_session(client, ctx)

        self.assertIn("2probe", server.websocket_packets)
        self.assertIn("5", server.websocket_packets)
        self.assertIn(f"41/{protocol_module.NS}", server.websocket_packets)

    async def test_open_authenticated_session_uses_stored_token_without_pairing(
        self,
    ) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        with tempfile.TemporaryDirectory() as config_root:
            token_file = Path(config_root) / ".storage/test-token.txt"
            token_file.parent.mkdir(parents=True)
            token_file.write_text(STORED_TOKEN, encoding="utf-8")

            async with (
                FakeDHEEngineIOServer(protocol_module.NS) as server,
                aiohttp.ClientSession() as session,
            ):
                client_module.async_get_clientsession = Mock(return_value=session)
                client = DHEClient(
                    _FakeHass(asyncio.get_running_loop(), config_root=config_root),
                    server.host,
                    server.port,
                    ".storage/test-token.txt",
                    "DHE",
                )
                server.queue_authentication()

                ctx = await DHEClient._open_authenticated_session(
                    client,
                    token_request_timeout_seconds=1.0,
                )
                await DHEClient._close_session(client, ctx)

        self.assertFalse(client._pairing_active)
        self.assertFalse(client._require_pairing_confirmation)
        self.assertTrue(
            any(
                '"token":"stored-token-fixture-000001"' in packet
                for packet in server.posted_packets
            ),
            server.posted_packets,
        )
        self.assertFalse(
            any(
                '"token":""' in packet and '["token_request"' in packet
                for packet in server.posted_packets
            ),
            server.posted_packets,
        )

    async def test_stored_token_pairing_request_is_auth_failure(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEAuthError = client_module.DHEAuthError
        DHEClient = client_module.DHEClient

        with tempfile.TemporaryDirectory() as config_root:
            token_file = Path(config_root) / ".storage/test-token.txt"
            token_file.parent.mkdir(parents=True)
            token_file.write_text(STORED_TOKEN, encoding="utf-8")

            async with (
                FakeDHEEngineIOServer(protocol_module.NS) as server,
                aiohttp.ClientSession() as session,
            ):
                client_module.async_get_clientsession = Mock(return_value=session)
                client = DHEClient(
                    _FakeHass(asyncio.get_running_loop(), config_root=config_root),
                    server.host,
                    server.port,
                    ".storage/test-token.txt",
                    "DHE",
                )
                server.queue_pairing_request()
                server.queue_pairing_result(True)
                server.queue_authentication()

                with self.assertRaisesRegex(DHEAuthError, "Stored DHE token"):
                    await DHEClient._open_authenticated_session(
                        client,
                        token_request_timeout_seconds=1.0,
                    )

            saved_token = token_file.read_text(encoding="utf-8")

        self.assertEqual(saved_token, STORED_TOKEN)
        self.assertFalse(client._pairing_active)
        self.assertFalse(client._pairing_request_seen)
        self.assertFalse(client._require_pairing_confirmation)
        self.assertTrue(
            any(
                '"token":"stored-token-fixture-000001"' in packet
                and '["token_request"' in packet
                for packet in server.posted_packets
            ),
            server.posted_packets,
        )

    async def test_stored_token_refresh_response_is_saved_and_authenticated(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        with tempfile.TemporaryDirectory() as config_root:
            token_file = Path(config_root) / ".storage/test-token.txt"
            token_file.parent.mkdir(parents=True)
            token_file.write_text(STORED_TOKEN, encoding="utf-8")

            async with (
                FakeDHEEngineIOServer(protocol_module.NS) as server,
                aiohttp.ClientSession() as session,
            ):
                client_module.async_get_clientsession = Mock(return_value=session)
                client = DHEClient(
                    _FakeHass(asyncio.get_running_loop(), config_root=config_root),
                    server.host,
                    server.port,
                    ".storage/test-token.txt",
                    "DHE",
                )
                server.queue_token_response(PAIRING_TOKEN)
                server.queue_authentication()

                ctx = await DHEClient._open_authenticated_session(
                    client,
                    token_request_timeout_seconds=1.0,
                )
                await DHEClient._close_session(client, ctx)

            saved_token = token_file.read_text(encoding="utf-8")

        self.assertEqual(saved_token, PAIRING_TOKEN)
        self.assertFalse(client._pairing_active)
        self.assertFalse(client._pairing_request_seen)
        self.assertFalse(client._require_pairing_confirmation)

    async def test_stored_token_pairing_rejection_is_auth_failure(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEAuthError = client_module.DHEAuthError
        DHEClient = client_module.DHEClient

        with tempfile.TemporaryDirectory() as config_root:
            token_file = Path(config_root) / ".storage/test-token.txt"
            token_file.parent.mkdir(parents=True)
            token_file.write_text(STORED_TOKEN, encoding="utf-8")

            async with (
                FakeDHEEngineIOServer(protocol_module.NS) as server,
                aiohttp.ClientSession() as session,
            ):
                client_module.async_get_clientsession = Mock(return_value=session)
                client = DHEClient(
                    _FakeHass(asyncio.get_running_loop(), config_root=config_root),
                    server.host,
                    server.port,
                    ".storage/test-token.txt",
                    "DHE",
                )
                server.queue_pairing_result(False)

                with self.assertRaisesRegex(DHEAuthError, "Stored DHE token"):
                    await DHEClient._open_authenticated_session(
                        client,
                        token_request_timeout_seconds=1.0,
                    )

            saved_token = token_file.read_text(encoding="utf-8")

        self.assertEqual(saved_token, STORED_TOKEN)

    async def test_runtime_without_startup_values_marks_auth_failed(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient
        previous_timeout = client_module.RUNTIME_STARTUP_PROOF_TIMEOUT_SECONDS
        client_module.RUNTIME_STARTUP_PROOF_TIMEOUT_SECONDS = 0.1
        try:
            with tempfile.TemporaryDirectory() as config_root:
                token_file = Path(config_root) / ".storage/test-token.txt"
                token_file.parent.mkdir(parents=True)
                token_file.write_text(STORED_TOKEN, encoding="utf-8")

                async with (
                    FakeDHEEngineIOServer(protocol_module.NS) as server,
                    aiohttp.ClientSession() as session,
                ):
                    client_module.async_get_clientsession = Mock(return_value=session)
                    client = DHEClient(
                        _FakeHass(asyncio.get_running_loop(), config_root=config_root),
                        server.host,
                        server.port,
                        ".storage/test-token.txt",
                        "DHE",
                    )
                    server.queue_token_response(PAIRING_TOKEN)
                    server.queue_authentication()

                    await DHEClient.start(client)
                    auth_failed_seen = False
                    for _attempt in range(40):
                        if client.diagnostic_state.get("connection_state") == "auth_failed":
                            auth_failed_seen = True
                            break
                        await asyncio.sleep(0.05)
                    await DHEClient.stop(client)

                saved_token = token_file.read_text(encoding="utf-8")
        finally:
            client_module.RUNTIME_STARTUP_PROOF_TIMEOUT_SECONDS = previous_timeout

        self.assertEqual(saved_token, PAIRING_TOKEN)
        self.assertTrue(auth_failed_seen)
        self.assertEqual(client.diagnostic_state["connection_state"], "stopped")
        self.assertFalse(client.available)

    def test_web_interface_version_does_not_prove_runtime_startup(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient
        client = DHEClient.__new__(DHEClient)
        client._last_measurements = {protocol_module.ID_PROTOCOL_VERSION: "1.9.00"}

        self.assertFalse(DHEClient._has_runtime_startup_proof(client))

        client._last_measurements[protocol_module.ID_DEVICE_STATUS] = 1

        self.assertTrue(DHEClient._has_runtime_startup_proof(client))

    async def test_runtime_startup_value_allows_connected_state(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient
        previous_timeout = client_module.RUNTIME_STARTUP_PROOF_TIMEOUT_SECONDS
        client_module.RUNTIME_STARTUP_PROOF_TIMEOUT_SECONDS = 1.0
        try:
            with tempfile.TemporaryDirectory() as config_root:
                token_file = Path(config_root) / ".storage/test-token.txt"
                token_file.parent.mkdir(parents=True)
                token_file.write_text(STORED_TOKEN, encoding="utf-8")

                async with (
                    FakeDHEEngineIOServer(protocol_module.NS) as server,
                    aiohttp.ClientSession() as session,
                ):
                    client_module.async_get_clientsession = Mock(return_value=session)
                    client = DHEClient(
                        _FakeHass(asyncio.get_running_loop(), config_root=config_root),
                        server.host,
                        server.port,
                        ".storage/test-token.txt",
                        "DHE",
                    )
                    server.queue_token_response(PAIRING_TOKEN)
                    server.queue_authentication()
                    server.queue_event(
                        "message",
                        {
                            "command": protocol_module.ODB_SET_COMMAND,
                            "value": {
                                "id": protocol_module.ID_DEVICE_STATUS,
                                "value": 1,
                            },
                        },
                    )

                    await DHEClient.start(client)
                    for _attempt in range(40):
                        if client.diagnostic_state.get("connection_state") == "connected":
                            break
                        await asyncio.sleep(0.05)
                    connected_state = client.diagnostic_state["connection_state"]
                    available = client.available
                    await DHEClient.stop(client)

                saved_token = token_file.read_text(encoding="utf-8")
        finally:
            client_module.RUNTIME_STARTUP_PROOF_TIMEOUT_SECONDS = previous_timeout

        self.assertEqual(saved_token, PAIRING_TOKEN)
        self.assertEqual(connected_state, "connected")
        self.assertTrue(available)

    async def test_stored_token_auth_session_close_is_auth_failure(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEAuthError = client_module.DHEAuthError
        DHEClient = client_module.DHEClient

        with tempfile.TemporaryDirectory() as config_root:
            token_file = Path(config_root) / ".storage/test-token.txt"
            token_file.parent.mkdir(parents=True)
            token_file.write_text(STORED_TOKEN, encoding="utf-8")

            async with (
                FakeDHEEngineIOServer(protocol_module.NS) as server,
                aiohttp.ClientSession() as session,
            ):
                client_module.async_get_clientsession = Mock(return_value=session)
                client = DHEClient(
                    _FakeHass(asyncio.get_running_loop(), config_root=config_root),
                    server.host,
                    server.port,
                    ".storage/test-token.txt",
                    "DHE",
                )
                server.queue_socket_close()

                with self.assertRaisesRegex(DHEAuthError, "Stored DHE token"):
                    await DHEClient._open_authenticated_session(
                        client,
                        token_request_timeout_seconds=1.0,
                    )

            saved_token = token_file.read_text(encoding="utf-8")

        self.assertEqual(saved_token, STORED_TOKEN)
        self.assertFalse(client._pairing_active)
        self.assertFalse(client._require_pairing_confirmation)
        self.assertTrue(
            any(
                '"token":"stored-token-fixture-000001"' in packet
                and '["token_request"' in packet
                for packet in server.posted_packets
            ),
            server.posted_packets,
        )

    async def test_validate_setup_authentication_accepts_pairing_result_flow(
        self,
    ) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        _mock_pairing_notifications()
        DHEClient = client_module.DHEClient

        with tempfile.TemporaryDirectory() as config_root:
            async with (
                FakeDHEEngineIOServer(protocol_module.NS) as server,
                aiohttp.ClientSession() as session,
            ):
                    client_module.async_get_clientsession = Mock(return_value=session)
                    client = DHEClient(
                        _FakeHass(asyncio.get_running_loop(), config_root=config_root),
                        server.host,
                        server.port,
                        ".storage/test-token.txt",
                        "DHE",
                    )
                    server.queue_pairing_request()
                    server.queue_pairing_result(True)
                    server.queue_token_response(PAIRING_TOKEN)
                    server.queue_authentication()
                    server.queue_device_info()

                    await DHEClient.validate_setup_authentication(
                        client,
                        timeout_seconds=2.0,
                    )

            token_file = Path(config_root) / ".storage/test-token.txt"
            saved_token = token_file.read_text(encoding="utf-8")

        self.assertEqual(saved_token, PAIRING_TOKEN)
        self.assertFalse(client._pairing_active)
        self.assertFalse(client._require_pairing_confirmation)
        self.assertFalse(client._manual_pairing_requested)
        self.assertEqual(client.last_device_info["wlan_mac"], "AA-BB-CC-DD-EE-FF")
        self.assertTrue(
            any(
                '"token":""' in packet and '["token_request"' in packet
                for packet in server.posted_packets
            ),
            server.posted_packets,
        )
        self.assertTrue(
            any(
                '"token":"pairing-token-fixture-0001"' in packet
                and '["token_request"' in packet
                for packet in server.posted_packets
            ),
            server.posted_packets,
        )

    async def test_repair_pairing_replaces_invalid_token_with_fake_dhe(
        self,
    ) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        _mock_pairing_notifications()
        DHEClient = client_module.DHEClient
        invalid_token = "invalid-token-fixture-000001"

        with tempfile.TemporaryDirectory() as config_root:
            token_file = Path(config_root) / ".storage/test-token.txt"
            token_file.parent.mkdir(parents=True)
            token_file.write_text(invalid_token, encoding="utf-8")

            async with (
                FakeDHEEngineIOServer(protocol_module.NS) as server,
                aiohttp.ClientSession() as session,
            ):
                client_module.async_get_clientsession = Mock(return_value=session)
                client = DHEClient(
                    _FakeHass(asyncio.get_running_loop(), config_root=config_root),
                    server.host,
                    server.port,
                    ".storage/test-token.txt",
                    "DHE",
                )
                server.queue_pairing_request()
                server.queue_pairing_result(True)
                server.queue_token_response(PAIRING_TOKEN)
                server.queue_authentication()
                server.queue_event(
                    "message",
                    {
                        "command": protocol_module.ODB_SET_COMMAND,
                        "value": {
                            "id": protocol_module.ID_DEVICE_STATUS,
                            "value": 1,
                        },
                    },
                )

                self.assertTrue(await DHEClient.repair_pairing(client))
                await asyncio.wait_for(client._ready.wait(), timeout=2)
                await DHEClient.stop(client)

            saved_token = token_file.read_text(encoding="utf-8")

        self.assertEqual(saved_token, PAIRING_TOKEN)
        self.assertFalse(client._manual_pairing_requested)
        self.assertFalse(client._require_pairing_confirmation)
        self.assertTrue(
            any(
                '"token":""' in packet and '["token_request"' in packet
                for packet in server.posted_packets
            ),
            server.posted_packets,
        )
        self.assertTrue(
            any(PAIRING_TOKEN in packet for packet in server.posted_packets),
            server.posted_packets,
        )
        self.assertFalse(
            any(invalid_token in packet for packet in server.posted_packets),
            server.posted_packets,
        )

    async def test_validate_setup_authentication_redacts_pairing_result_in_logs(
        self,
    ) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        _mock_pairing_notifications()
        DHEClient = client_module.DHEClient

        with tempfile.TemporaryDirectory() as config_root:
            async with (
                FakeDHEEngineIOServer(protocol_module.NS) as server,
                aiohttp.ClientSession() as session,
            ):
                client_module.async_get_clientsession = Mock(return_value=session)
                client = DHEClient(
                    _FakeHass(asyncio.get_running_loop(), config_root=config_root),
                    server.host,
                    server.port,
                    ".storage/test-token.txt",
                    "DHE",
                )
                sensitive_pairing_result = {
                    "result": "accepted",
                    "token": "should-not-log",
                    "code": "secret-code",
                }
                server.queue_pairing_request()
                server.queue_event("pairing_result", sensitive_pairing_result)
                server.queue_token_response(PAIRING_TOKEN)
                server.queue_authentication()
                server.queue_device_info()

                with self.assertLogs(
                    "custom_components.stiebel_dhe_connect.client_transport_auth",
                    level="INFO",
                ) as log_context:
                    await DHEClient.validate_setup_authentication(
                        client,
                        timeout_seconds=2.0,
                    )

        logs = "\n".join(log_context.output)
        self.assertNotIn("should-not-log", logs)
        self.assertNotIn("secret-code", logs)
        self.assertIn("<redacted>", logs)

    async def test_manual_pairing_waits_for_result_when_token_arrives_first(
        self,
    ) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        _mock_pairing_notifications()
        DHEClient = client_module.DHEClient

        with tempfile.TemporaryDirectory() as config_root:
            async with FakeDHEEngineIOServer(
                protocol_module.NS,
                websocket_enabled=False,
            ) as server, aiohttp.ClientSession() as session:
                client_module.async_get_clientsession = Mock(return_value=session)
                client = DHEClient(
                    _FakeHass(asyncio.get_running_loop(), config_root=config_root),
                    server.host,
                    server.port,
                    ".storage/test-token.txt",
                    "DHE",
                )
                client._begin_manual_pairing(
                    "setup_requested",
                    "waiting for confirmation",
                    notify=False,
                )
                server.queue_token_response(PAIRING_TOKEN)
                server.queue_pairing_result(True)

                token = await DHEClient._request_initial_token(
                    client,
                    timeout_seconds=2.0,
                )

            token_file = Path(config_root) / ".storage/test-token.txt"
            saved_token = token_file.read_text(encoding="utf-8")

        self.assertEqual(token, PAIRING_TOKEN)
        self.assertEqual(saved_token, PAIRING_TOKEN)
        self.assertTrue(client._pairing_confirmed_success)
        self.assertTrue(
            any(
                '"token":"pairing-token-fixture-0001"' in packet
                and '["authenticate"' in packet
                for packet in server.posted_packets
            ),
            server.posted_packets,
        )

    async def test_pairing_rejection_from_fake_dhe_fails_before_saving_token(
        self,
    ) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        _mock_pairing_notifications()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError

        temp_dir = tempfile.TemporaryDirectory()
        config_root = temp_dir.name
        try:
            async with (
                FakeDHEEngineIOServer(protocol_module.NS) as server,
                aiohttp.ClientSession() as session,
            ):
                client_module.async_get_clientsession = Mock(return_value=session)
                client = DHEClient(
                    _FakeHass(asyncio.get_running_loop(), config_root=config_root),
                    server.host,
                    server.port,
                    ".storage/test-token.txt",
                    "DHE",
                )
                client._begin_manual_pairing(
                    "setup_requested",
                    "waiting for confirmation",
                    notify=False,
                )
                server.queue_pairing_request()
                server.queue_pairing_result(False)
                server.queue_token_response(PAIRING_TOKEN)

                with self.assertLogs(
                    f"{PACKAGE_NAME}.client_pairing",
                    level="WARNING",
                ), self.assertRaisesRegex(
                    DHEError,
                    "Pairing confirmation rejected on DHE",
                ):
                    await DHEClient._request_initial_token(
                        client,
                        timeout_seconds=1.0,
                    )
        finally:
            temp_dir.cleanup()

            token_file = Path(config_root) / ".storage/test-token.txt"

        self.assertTrue(client._pairing_failed_explicit)
        self.assertFalse(token_file.exists())

    async def test_runtime_closed_packet_marks_session_reconnecting(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        dhe_client_cls = client_module.DHEClient
        client_types_module = sys.modules[f"{PACKAGE_NAME}.client_types"]
        DHESessionClosed = client_types_module.DHESessionClosed

        async with (
            FakeDHEEngineIOServer(protocol_module.NS) as server,
            _connected_fake_client(client_module, server) as (
                DHEClient,
                client,
                ctx,
            ),
        ):
            server.queue_socket_close()
            events = await dhe_client_cls._read_polling_events_once(client, ctx)

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].name, "__closed")
            with self.assertRaises(DHESessionClosed):
                await dhe_client_cls._handle_runtime_event(client, events[0])

        self.assertEqual(
            client.diagnostic_state["connection_state"],
            "reconnecting",
        )
        self.assertEqual(
            client.diagnostic_state["last_reconnect_reason"],
            "DHE closed Socket.IO session",
        )

    async def test_partial_websocket_shutdown_marks_session_reconnecting(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        client_types_module = sys.modules[f"{PACKAGE_NAME}.client_types"]
        DHESessionClosed = client_types_module.DHESessionClosed

        async with (
            FakeDHEEngineIOServer(protocol_module.NS) as server,
            _connected_fake_client(client_module, server) as (
                DHEClient,
                client,
                ctx,
            ),
        ):
            await DHEClient._upgrade_to_websocket(client, ctx)
            if server.websocket_upgraded is not None:
                await asyncio.wait_for(server.websocket_upgraded.wait(), timeout=1)

            await server.close_active_websockets()
            events = await DHEClient._read_websocket_events_once(client, ctx)

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].name, "__closed")
            with self.assertRaises(DHESessionClosed):
                await DHEClient._handle_runtime_event(client, events[0])

        self.assertEqual(
            client.diagnostic_state["connection_state"],
            "reconnecting",
        )
        self.assertEqual(
            client.diagnostic_state["last_reconnect_reason"],
            "DHE closed Socket.IO session",
        )

    async def test_malformed_runtime_payloads_are_counted_and_ignored(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()

        async with (
            FakeDHEEngineIOServer(protocol_module.NS) as server,
            _connected_fake_client(client_module, server) as (
                _DHEClient,
                client,
                ctx,
            ),
        ):
            server.queue_event("message", "not-a-dict")
            await _handle_next_polling_event(client, ctx)
            server.queue_event("message", {"value": 1})
            await _handle_next_polling_event(client, ctx)
            server.queue_event(
                "message",
                {"command": protocol_module.ODB_SET_COMMAND, "value": []},
            )
            await _handle_next_polling_event(client, ctx)
            server.queue_event(
                "message",
                {
                    "command": protocol_module.ODB_SET_COMMAND,
                    "value": {"id": "bad-id", "value": 1},
                },
            )
            await _handle_next_polling_event(client, ctx)
            server.queue_event(
                "message",
                {
                    "command": protocol_module.ODB_SET_COMMAND,
                    "value": {
                        "id": protocol_module.ID_WATER_FLOW,
                        "name": "ODB_Is_P_Norm",
                        "value": 27,
                    },
                },
            )
            await _handle_next_polling_event(client, ctx)

        self.assertEqual(client._runtime_parser_stats["invalid_message_payload"], 1)
        self.assertEqual(client._runtime_parser_stats["invalid_command"], 1)
        self.assertEqual(client._runtime_parser_stats["invalid_odb_payload"], 1)
        self.assertEqual(client._runtime_parser_stats["invalid_odb_id"], 2)
        self.assertEqual(client._last_measurements, {})

    async def test_unknown_radio_and_weather_payloads_are_ignored_safely(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()

        async with (
            FakeDHEEngineIOServer(protocol_module.NS) as server,
            _connected_fake_client(client_module, server) as (
                _DHEClient,
                client,
                ctx,
            ),
        ):
            await _queue_message_and_handle(
                server,
                client,
                ctx,
                "set:ste.app.radio:unknown",
                {"unexpected": ["payload"]},
            )
            await _queue_message_and_handle(
                server,
                client,
                ctx,
                "set:ste.app.weather:unknown",
                {"unexpected": "payload"},
            )

        self.assertEqual(client._runtime_parser_stats["radio_unhandled"], 1)
        self.assertEqual(client._runtime_parser_stats["unhandled"], 1)
        self.assertEqual(client._last_measurements, {})

    async def test_reconnect_during_command_retries_after_session_replacement(
        self,
    ) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        command_runner_module = sys.modules[f"{PACKAGE_NAME}.client_command_runner"]

        async with (
            FakeDHEEngineIOServer(protocol_module.NS) as server,
            _connected_fake_client(client_module, server) as (
                DHEClient,
                client,
                ctx,
            ),
        ):
            ctx.websocket = _ClosedWebSocket()
            restored_ctx: Any | None = None

            async def _restore_session_after_reconnect() -> Any:
                while client._ready.is_set():
                    await asyncio.sleep(0.01)
                new_ctx = await DHEClient._open_session(client, "stored-token")
                client._ctx = new_ctx
                client._available = True
                client._ready.set()
                return new_ctx

            restore_task = asyncio.create_task(_restore_session_after_reconnect())
            with patch.object(
                command_runner_module,
                "COMMAND_RETRY_DELAY_SECONDS",
                0.01,
            ):
                command_task = asyncio.create_task(
                    DHEClient.set_temperature(client, 42.0)
                )
                restored_ctx = await asyncio.wait_for(restore_task, timeout=1)
                assign_packet = await server.wait_for_posted_packet(
                    protocol_module.ODB_ASSIGN_COMMAND,
                    timeout=1,
                )
                self.assertIn(
                    f'"id":{protocol_module.ID_SETPOINT_REQUEST}',
                    assign_packet,
                )
                await _queue_message_and_handle(
                    server,
                    client,
                    restored_ctx,
                    protocol_module.ODB_ASSIGN_COMMAND,
                    {
                        "id": protocol_module.ID_SETPOINT,
                        "value": 420,
                    },
                )
                result = await asyncio.wait_for(command_task, timeout=1)

        self.assertEqual(result, 42.0)
        self.assertEqual(client.last_setpoint, 42.0)
        self.assertIsNot(restored_ctx, ctx)

    async def test_set_water_heating_enabled_confirms_via_fake_dhe_readback(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        async with (
            FakeDHEEngineIOServer(protocol_module.NS) as server,
            aiohttp.ClientSession() as session,
        ):
                client_module.async_get_clientsession = Mock(return_value=session)
                client = DHEClient(
                    _FakeHass(asyncio.get_running_loop()),
                    server.host,
                    server.port,
                    ".storage/test-token",
                    "DHE",
                )

                ctx = await DHEClient._open_session(client, "stored-token")
                client._ctx = ctx
                client._ready.set()
                client._available = True

                command_task = asyncio.create_task(
                    DHEClient.set_water_heating_enabled(client, False)
                )

                assign_packet = await server.wait_for_posted_packet(
                    protocol_module.ODB_ASSIGN_COMMAND,
                )
                self.assertIn(f'"id":{protocol_module.ID_WATER_HEATING_ENABLED}', assign_packet)

                server.queue_event(
                    "message",
                    {
                        "command": protocol_module.ODB_ASSIGN_COMMAND,
                        "value": {
                            "id": protocol_module.ID_WATER_HEATING_ENABLED,
                            "value": protocol_module.WATER_HEATING_OFF_RAW,
                        },
                    },
                )
                await _handle_next_polling_event(client, ctx)
                result = await asyncio.wait_for(command_task, timeout=1)
                await DHEClient._close_session(client, ctx)

        self.assertFalse(result)
        self.assertTrue(
            any(
                f'"id":{protocol_module.ID_SETPOINT_REQUEST}' in packet
                and f'"value":{protocol_module.SET_REQ_OFF_VALUE}' in packet
                for packet in server.posted_packets
            ),
            server.posted_packets,
        )

    async def test_set_temperature_confirms_via_fake_dhe_setpoint_readback(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()

        async with (
            FakeDHEEngineIOServer(protocol_module.NS) as server,
            _connected_fake_client(client_module, server) as (
                DHEClient,
                client,
                ctx,
            ),
        ):
                command_task = asyncio.create_task(
                    DHEClient.set_temperature(client, 41.0)
                )

                assign_packet = await server.wait_for_posted_packet(
                    protocol_module.ODB_ASSIGN_COMMAND,
                )
                self.assertIn(f'"id":{protocol_module.ID_SETPOINT_REQUEST}', assign_packet)

                await _queue_message_and_handle(
                    server,
                    client,
                    ctx,
                    protocol_module.ODB_ASSIGN_COMMAND,
                    {
                        "id": protocol_module.ID_SETPOINT,
                        "value": 410,
                    },
                )
                result = await asyncio.wait_for(command_task, timeout=1)

        self.assertEqual(result, 41.0)
        self.assertEqual(client.last_setpoint, 41.0)

    async def test_set_temperature_accepts_delayed_explicit_readback(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()

        async with (
            FakeDHEEngineIOServer(protocol_module.NS) as server,
            _connected_fake_client(client_module, server) as (
                DHEClient,
                client,
                ctx,
            ),
        ):
                command_task = asyncio.create_task(
                    DHEClient.set_temperature(client, 43.0)
                )

                await server.wait_for_posted_packet(
                    protocol_module.ODB_ASSIGN_COMMAND,
                )
                readback_request = await server.wait_for_posted_packet(
                    protocol_module.ODB_GET_COMMAND,
                )
                self.assertIn(f'"id":{protocol_module.ID_SETPOINT}', readback_request)
                await asyncio.sleep(0.05)
                await _queue_message_and_handle(
                    server,
                    client,
                    ctx,
                    protocol_module.ODB_GET_COMMAND,
                    {
                        "id": protocol_module.ID_SETPOINT,
                        "value": 430,
                    },
                )
                result = await asyncio.wait_for(command_task, timeout=1)

        self.assertEqual(result, 43.0)
        self.assertEqual(client.last_setpoint, 43.0)

    async def test_set_temperature_uses_sequential_setpoint_addresses(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()

        async with (
            FakeDHEEngineIOServer(protocol_module.NS) as server,
            _connected_fake_client(client_module, server) as (
                DHEClient,
                client,
                ctx,
            ),
        ):
                first_task = asyncio.create_task(
                    DHEClient.set_temperature(client, 41.0)
                )
                first_packets = await server.wait_for_posted_packet_count(
                    protocol_module.ODB_ASSIGN_COMMAND,
                    1,
                )
                first_packet = first_packets[0]
                await _queue_message_and_handle(
                    server,
                    client,
                    ctx,
                    protocol_module.ODB_ASSIGN_COMMAND,
                    {
                        "id": protocol_module.ID_SETPOINT,
                        "value": 410,
                    },
                )
                await asyncio.wait_for(first_task, timeout=1)

                second_task = asyncio.create_task(
                    DHEClient.set_temperature(client, 41.0)
                )
                second_packets = await server.wait_for_posted_packet_count(
                    protocol_module.ODB_ASSIGN_COMMAND,
                    2,
                )
                second_packet = second_packets[-1]
                await _queue_message_and_handle(
                    server,
                    client,
                    ctx,
                    protocol_module.ODB_ASSIGN_COMMAND,
                    {
                        "id": protocol_module.ID_SETPOINT,
                        "value": 410,
                    },
                )
                await asyncio.wait_for(second_task, timeout=1)

        first_request_value = _extract_assign_value(first_packet)
        second_request_value = _extract_assign_value(second_packet)
        self.assertNotEqual(
            first_request_value,
            second_request_value,
            (first_packet, second_packet),
        )

    async def test_set_temperature_memory_confirms_generation_readback(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()

        async with (
            FakeDHEEngineIOServer(protocol_module.NS) as server,
            _connected_fake_client(client_module, server) as (
                DHEClient,
                client,
                ctx,
            ),
        ):
                command_task = asyncio.create_task(
                    DHEClient.set_temperature_memory(client, 1, 39.5)
                )

                await server.wait_for_posted_packet_count(
                    protocol_module.TEMP_MEMORY_GET_COMMAND,
                    1,
                )
                await _queue_message_and_handle(
                    server,
                    client,
                    ctx,
                    protocol_module.TEMP_MEMORY_SET_COMMAND,
                    [{"id": 0, "name": "Eco", "temperature": 38.0}],
                )

                assign_packet = await server.wait_for_posted_packet(
                    protocol_module.TEMP_MEMORY_ASSIGN_COMMAND,
                )
                self.assertIn('"operation":"add_change"', assign_packet)
                self.assertIn('"temperature":39.5', assign_packet)

                await server.wait_for_posted_packet_count(
                    protocol_module.TEMP_MEMORY_GET_COMMAND,
                    2,
                )
                await _queue_message_and_handle(
                    server,
                    client,
                    ctx,
                    protocol_module.TEMP_MEMORY_SET_COMMAND,
                    [{"id": 0, "name": "Eco", "temperature": 39.5}],
                )
                result = await asyncio.wait_for(command_task, timeout=1)

        self.assertEqual(result, 39.5)
        self.assertEqual(
            client._last_measurements[protocol_module.ID_TEMPERATURE_MEMORY_1],
            39.5,
        )

    async def test_shower_timer_reset_recovers_remaining_from_configured_duration(
        self,
    ) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()

        async with (
            FakeDHEEngineIOServer(protocol_module.NS) as server,
            _connected_fake_client(client_module, server) as (
                DHEClient,
                client,
                ctx,
            ),
        ):
                client._last_measurements[protocol_module.ID_SHOWER_TIMER_DURATION] = 4.0
                client._last_measurements[protocol_module.ID_SHOWER_TIMER_REMAINING] = 0.0
                client._last_measurements[protocol_module.ID_SHOWER_TIMER_ACTIVATION] = True
                command_task = asyncio.create_task(DHEClient.reset_shower_timer(client))

                reset_packet = await server.wait_for_posted_packet(
                    f"assign:{protocol_module.SHOWER_TIMER_PATH}:reset",
                )
                self.assertIn('"value":true', reset_packet)
                await _queue_message_and_handle(
                    server,
                    client,
                    ctx,
                    f"set:{protocol_module.SHOWER_TIMER_PATH}:reset",
                    True,
                )
                result = await asyncio.wait_for(command_task, timeout=1)

        self.assertTrue(result)
        self.assertEqual(
            client._last_measurements[protocol_module.ID_SHOWER_TIMER_REMAINING],
            4.0,
        )
        self.assertFalse(
            client._last_measurements[protocol_module.ID_SHOWER_TIMER_ACTIVATION]
        )

    async def test_add_radio_favorite_selects_station_with_fake_dhe_readbacks(
        self,
    ) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        station = {
            "Id": 4301,
            "Name": "Code Blue FM",
            "City": "Local",
        }

        async with (
            FakeDHEEngineIOServer(protocol_module.NS) as server,
            _connected_fake_client(client_module, server) as (
                DHEClient,
                client,
                ctx,
            ),
        ):
                command_task = asyncio.create_task(
                    DHEClient.add_radio_favorite(client, station, select=True)
                )

                await server.wait_for_posted_packet(
                    protocol_module.RADIO_FAVORITES_GET_COMMAND,
                )
                await _queue_message_and_handle(
                    server,
                    client,
                    ctx,
                    protocol_module.RADIO_FAVORITES_SET_COMMAND,
                    [],
                )

                favorite_packet = await server.wait_for_posted_packet(
                    protocol_module.RADIO_FAVORITE_ASSIGN_COMMAND,
                )
                self.assertIn('"value":4301', favorite_packet)
                await _queue_message_and_handle(
                    server,
                    client,
                    ctx,
                    protocol_module.RADIO_FAVORITES_SET_COMMAND,
                    [station],
                )

                station_packet = await server.wait_for_posted_packet(
                    protocol_module.RADIO_STATION_ASSIGN_COMMAND,
                )
                self.assertIn('"value":4301', station_packet)
                await _queue_message_and_handle(
                    server,
                    client,
                    ctx,
                    f"set:{protocol_module.RADIO_PATH}:station",
                    station,
                )
                result = await asyncio.wait_for(command_task, timeout=1)

        self.assertTrue(result)
        self.assertEqual(client.last_radio_state["station"]["Id"], 4301)
        self.assertEqual(client.last_radio_state["favorites"][0]["Id"], 4301)

    async def test_remove_radio_favorite_syncs_with_fake_dhe_readbacks(
        self,
    ) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        station = {
            "Id": 4302,
            "Name": "Code Green FM",
            "City": "Local",
        }

        async with (
            FakeDHEEngineIOServer(protocol_module.NS) as server,
            _connected_fake_client(client_module, server) as (
                DHEClient,
                client,
                ctx,
            ),
        ):
                command_task = asyncio.create_task(
                    DHEClient.remove_radio_favorite(client, station)
                )

                await server.wait_for_posted_packet(
                    protocol_module.RADIO_FAVORITES_GET_COMMAND,
                )
                await _queue_message_and_handle(
                    server,
                    client,
                    ctx,
                    protocol_module.RADIO_FAVORITES_SET_COMMAND,
                    [station],
                )

                favorite_packet = await server.wait_for_posted_packet(
                    protocol_module.RADIO_FAVORITE_ASSIGN_COMMAND,
                )
                self.assertIn('"value":4302', favorite_packet)
                await _queue_message_and_handle(
                    server,
                    client,
                    ctx,
                    protocol_module.RADIO_FAVORITES_SET_COMMAND,
                    [],
                )
                result = await asyncio.wait_for(command_task, timeout=1)

        self.assertTrue(result)
        self.assertEqual(client.last_radio_state["favorites"], [])

    async def test_add_weather_favorite_selects_location_with_fake_dhe_readbacks(
        self,
    ) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        location = {
            "LocationId": "fixture-weather-1",
            "Name": "Fixture City",
            "Country": "Testland",
        }

        async with (
            FakeDHEEngineIOServer(protocol_module.NS) as server,
            _connected_fake_client(client_module, server) as (
                DHEClient,
                client,
                ctx,
            ),
        ):
                command_task = asyncio.create_task(
                    DHEClient.add_weather_favorite(client, location)
                )

                await server.wait_for_posted_packet(
                    protocol_module.WEATHER_FAVORITES_GET_COMMAND,
                )
                await _queue_message_and_handle(
                    server,
                    client,
                    ctx,
                    protocol_module.WEATHER_FAVORITES_SET_COMMAND,
                    [],
                )

                favorite_packet = await server.wait_for_posted_packet(
                    protocol_module.WEATHER_FAVORITE_ASSIGN_COMMAND,
                )
                self.assertIn('"LocationId":"fixture-weather-1"', favorite_packet)
                await _queue_message_and_handle(
                    server,
                    client,
                    ctx,
                    protocol_module.WEATHER_FAVORITES_SET_COMMAND,
                    [location],
                )

                location_packet = await server.wait_for_posted_packet(
                    protocol_module.WEATHER_LOCATION_GET_COMMAND,
                )
                self.assertIn('"value":"fixture-weather-1"', location_packet)
                await _queue_message_and_handle(
                    server,
                    client,
                    ctx,
                    protocol_module.WEATHER_LOCATION_SET_COMMAND,
                    {"Location": location},
                )
                result = await asyncio.wait_for(command_task, timeout=1)

        self.assertTrue(result)
        self.assertEqual(
            client.last_weather_state["location"]["LocationId"],
            "fixture-weather-1",
        )
        self.assertEqual(
            client.last_weather_state["favorites"][0]["LocationId"],
            "fixture-weather-1",
        )

    async def test_add_weather_favorite_sync_skips_existing_favorite_toggle(
        self,
    ) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        location = {
            "LocationId": "fixture-weather-existing",
            "Name": "Fixture Already",
            "Country": "Testland",
        }

        async with (
            FakeDHEEngineIOServer(protocol_module.NS) as server,
            _connected_fake_client(client_module, server) as (
                DHEClient,
                client,
                ctx,
            ),
        ):
                command_task = asyncio.create_task(
                    DHEClient.add_weather_favorite(client, location)
                )

                await server.wait_for_posted_packet(
                    protocol_module.WEATHER_FAVORITES_GET_COMMAND,
                )
                await _queue_message_and_handle(
                    server,
                    client,
                    ctx,
                    protocol_module.WEATHER_FAVORITES_SET_COMMAND,
                    [location],
                )
                result = await asyncio.wait_for(command_task, timeout=1)

        self.assertTrue(result)
        self.assertEqual(
            client.last_weather_state["favorites"][0]["LocationId"],
            "fixture-weather-existing",
        )
        self.assertFalse(
            any(
                protocol_module.WEATHER_FAVORITE_ASSIGN_COMMAND in packet
                for packet in server.posted_packets
            ),
            server.posted_packets,
        )

    async def test_remove_weather_favorite_confirms_with_fake_dhe_readback(
        self,
    ) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        location = {
            "LocationId": "fixture-weather-2",
            "Name": "Fixture Bay",
            "Country": "Testland",
        }

        async with (
            FakeDHEEngineIOServer(protocol_module.NS) as server,
            _connected_fake_client(client_module, server) as (
                DHEClient,
                client,
                ctx,
            ),
        ):
                command_task = asyncio.create_task(
                    DHEClient.remove_weather_favorite(client, location)
                )

                await server.wait_for_posted_packet(
                    protocol_module.WEATHER_FAVORITES_GET_COMMAND,
                )
                await _queue_message_and_handle(
                    server,
                    client,
                    ctx,
                    protocol_module.WEATHER_FAVORITES_SET_COMMAND,
                    [location],
                )

                favorite_packet = await server.wait_for_posted_packet(
                    protocol_module.WEATHER_FAVORITE_ASSIGN_COMMAND,
                )
                self.assertIn('"LocationId":"fixture-weather-2"', favorite_packet)
                await _queue_message_and_handle(
                    server,
                    client,
                    ctx,
                    protocol_module.WEATHER_FAVORITES_SET_COMMAND,
                    [],
                )
                result = await asyncio.wait_for(command_task, timeout=1)

        self.assertTrue(result)
        self.assertEqual(client.last_weather_state["favorites"], [])


class _FakeConfig:
    language = "en"

    def __init__(self, root: str | None = None) -> None:
        self._root = Path(root or tempfile.gettempdir())

    def path(self, value: str) -> str:
        path = Path(value)
        if path.is_absolute():
            return str(path)
        return str(self._root / path)


class _FakeHass:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        *,
        config_root: str | None = None,
    ) -> None:
        self.loop = loop
        self.config = _FakeConfig(config_root)

    def async_create_task(self, coro: Any, *, name: str | None = None) -> asyncio.Task[Any]:
        return asyncio.create_task(coro, name=name)

    async def async_add_executor_job(self, target: Any, *args: Any) -> Any:
        call = functools.partial(target, *args)
        return await self.loop.run_in_executor(None, call)


async def _handle_next_polling_event(client: Any, ctx: Any) -> None:
    for event in await client._read_polling_events_once(ctx):
        await client._handle_runtime_event(event)


if __name__ == "__main__":
    unittest.main()
