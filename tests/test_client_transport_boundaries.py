"""Transport edge cases close sessions and keep heartbeat traffic internal."""

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tests.client_behavior_support import make_client
from tests.client_test_support import PACKAGE_NAME


@pytest.fixture
async def device(monkeypatch):
    client, module = make_client(monkeypatch)
    return client, module, sys.modules[f"{PACKAGE_NAME}.client_transport"]


def websocket(transport, packets):
    return SimpleNamespace(
        closed=False,
        send_str=AsyncMock(),
        close=AsyncMock(),
        receive=AsyncMock(
            side_effect=[
                SimpleNamespace(type=transport.aiohttp.WSMsgType.TEXT, data=packet)
                for packet in packets
            ]
        ),
    )


@pytest.mark.parametrize("kind", ["polling", "websocket"])
@pytest.mark.parametrize(
    "packet,closed",
    [("", False), ("2", False), ("3", False), ("1", True), ("41/1.0.0", True)],
)
async def test_control_packets_do_not_escape_as_application_events(
    device, kind, packet, closed
):
    client, _, transport = device
    client._get_text = AsyncMock(return_value=packet)
    client._ctx.websocket = websocket(transport, [packet])
    client._send_websocket_packet = AsyncMock()
    events = await getattr(client, f"_read_{kind}_events_once")(client._ctx)
    assert [event.name for event in events] == (["__closed"] if closed else [])
    sender = client._post_packet if kind == "polling" else client._send_websocket_packet
    if packet == "2":
        sender.assert_awaited_once_with(client._ctx, "3")
    else:
        sender.assert_not_awaited()


async def test_poll_timeout_and_missing_websocket(device):
    client, _, transport = device
    client._get_text = AsyncMock(side_effect=TimeoutError())
    assert await client._read_polling_events_once(client._ctx) == []
    assert await client._read_websocket_events_once(client._ctx) == []
    with pytest.raises(transport.DHESessionClosed):
        await client._read_events_once(client._ctx)


@pytest.mark.parametrize(
    "failure", [OSError("connection lost"), RuntimeError("Session is closed")]
)
async def test_heartbeat_failure_requests_reconnect(device, failure):
    client, _, transport = device
    client._ctx.websocket = websocket(transport, [])
    client._ctx.ping_interval = 0
    client._send_websocket_packet = AsyncMock(side_effect=failure)
    await client._websocket_ping_loop(client._ctx)
    client._force_reconnect.assert_awaited_once()
    assert "Heartbeat failed" in client._force_reconnect.call_args.kwargs["reason"]


async def test_heartbeat_stopping_during_sleep_does_not_send(device, monkeypatch):
    client, _, transport = device
    client._ctx.websocket = websocket(transport, [])
    client._send_websocket_packet = AsyncMock()

    async def stop(_delay):
        client._stopped.set()

    monkeypatch.setattr(
        transport,
        "asyncio",
        SimpleNamespace(sleep=stop, CancelledError=asyncio.CancelledError),
    )
    await client._websocket_ping_loop(client._ctx)
    client._send_websocket_packet.assert_not_awaited()


@pytest.mark.parametrize(
    "failure", [OSError("connection lost"), RuntimeError("Session is closed")]
)
async def test_upgrade_failure_closes_socket_and_records_failure(device, failure):
    client, module, transport = device
    ws = websocket(transport, [])
    ws.receive.side_effect = failure
    client._connect_websocket = AsyncMock(return_value=ws)
    client._websocket_url_candidates = Mock(
        return_value=[("fixture", "sid", "ws://device.invalid")]
    )
    with pytest.raises(module.DHEError, match="upgrade failed"):
        await client._upgrade_to_websocket(client._ctx)
    assert ws.close.await_count >= 1
    assert client._ctx.websocket is None
    assert client._websocket_upgrade_failures == 1


async def test_upgrade_ignores_unrelated_packets_and_answers_ping(device):
    client, _, transport = device
    ws = websocket(transport, ["2", "3", "", "unexpected", "3probe"])
    client._connect_websocket = AsyncMock(return_value=ws)

    def capture(coro, _name):
        coro.close()

    client._create_background_task = Mock(side_effect=capture)
    await client._upgrade_to_websocket(client._ctx)
    assert [call.args[0] for call in ws.send_str.await_args_list] == [
        "2probe",
        "3",
        "5",
    ]
    assert client._ctx.websocket is ws
    ws.close.assert_not_awaited()


async def test_reconnect_old_context_does_not_detach_new_session(device):
    client, module, _ = device
    old = module.DHESession("old", "fixture")
    current = client._ctx
    client._close_session = AsyncMock()
    del client._force_reconnect
    await client._force_reconnect(old)
    assert client._ctx is current
    client._close_session.assert_awaited_once_with(old)
