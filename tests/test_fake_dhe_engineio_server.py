"""Transport tests backed by a lightweight fake DHE Engine.IO server."""

from __future__ import annotations

import asyncio
import json
from typing import Any
import unittest
from unittest.mock import Mock

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


class FakeDHEEngineIOServer:
    """Minimal Engine.IO v3 server for transport-level client tests."""

    def __init__(self, namespace: str) -> None:
        self.namespace = namespace
        self.host = "127.0.0.1"
        self.port = 0
        self.polling_sid = "polling-sid"
        self.websocket_sid = "websocket-sid"
        self.posted_packets: list[str] = []
        self.websocket_packets: list[str] = []
        self._poll_packets: asyncio.Queue[str] = asyncio.Queue()
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self.websocket_upgraded: asyncio.Event | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    async def __aenter__(self) -> FakeDHEEngineIOServer:
        self.websocket_upgraded = asyncio.Event()
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
        self._poll_packets.put_nowait(f"42/{self.namespace},{payload}")

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
        return web.Response(text="ok", content_type="text/plain")

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        websocket = web.WebSocketResponse(autoping=True)
        await websocket.prepare(request)
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
        return websocket


class TestFakeDHEEngineIOServer(unittest.IsolatedAsyncioTestCase):
    """Exercise real HTTP/WebSocket transport against the fake DHE server."""

    def test_websocket_timeout_preserves_idle_receive(self) -> None:
        transport_module = _load_component_module("client_transport")

        timeout = transport_module._websocket_timeout(8.0)

        if hasattr(timeout, "ws_receive"):
            self.assertIsNone(timeout.ws_receive)
            self.assertEqual(timeout.ws_close, 8.0)
        else:
            self.assertEqual(timeout, 8.0)

    async def test_client_polling_session_reads_fake_dhe_events(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        async with FakeDHEEngineIOServer(protocol_module.NS) as server:
            async with aiohttp.ClientSession() as session:
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

        async with FakeDHEEngineIOServer(protocol_module.NS) as server:
            async with aiohttp.ClientSession() as session:
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


if __name__ == "__main__":
    unittest.main()
