"""Transport tests backed by a lightweight fake DHE Engine.IO server."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
        self._poll_packets.put_nowait(f"42/{self.namespace},{payload}")

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

    async def test_set_water_heating_enabled_confirms_via_fake_dhe_readback(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        async with FakeDHEEngineIOServer(protocol_module.NS) as server:
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

        async with FakeDHEEngineIOServer(protocol_module.NS) as server:
            async with _connected_fake_client(client_module, server) as (
                DHEClient,
                client,
                ctx,
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

    async def test_set_temperature_memory_confirms_generation_readback(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()

        async with FakeDHEEngineIOServer(protocol_module.NS) as server:
            async with _connected_fake_client(client_module, server) as (
                DHEClient,
                client,
                ctx,
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

        async with FakeDHEEngineIOServer(protocol_module.NS) as server:
            async with _connected_fake_client(client_module, server) as (
                DHEClient,
                client,
                ctx,
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

        async with FakeDHEEngineIOServer(protocol_module.NS) as server:
            async with _connected_fake_client(client_module, server) as (
                DHEClient,
                client,
                ctx,
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

        async with FakeDHEEngineIOServer(protocol_module.NS) as server:
            async with _connected_fake_client(client_module, server) as (
                DHEClient,
                client,
                ctx,
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
    def path(self, value: str) -> str:
        return f"/tmp/{value}"


class _FakeHass:
    config = _FakeConfig()

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def async_create_task(self, coro: Any, *, name: str | None = None) -> asyncio.Task[Any]:
        return asyncio.create_task(coro, name=name)


async def _handle_next_polling_event(client: Any, ctx: Any) -> None:
    for event in await client._read_polling_events_once(ctx):
        await client._handle_runtime_event(event)


if __name__ == "__main__":
    unittest.main()
