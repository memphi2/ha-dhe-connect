"""Focused DHE client regression tests."""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock

from tests.client_test_support import (
    PACKAGE_NAME,
    _load_client,
    _load_component_module,
    _load_protocol,
)


class TestClientSession(unittest.IsolatedAsyncioTestCase):
    async def test_restart_after_reauth_restarts_running_client_with_fresh_token(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._command_lock = asyncio.Lock()
        client._token = "stale-token"
        runner = asyncio.create_task(asyncio.sleep(60))
        client._runner = runner
        client.stop = AsyncMock()
        client.start = AsyncMock()

        try:
            await DHEClient.restart_after_reauth(client)
        finally:
            runner.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await runner

        self.assertIsNone(client._token)
        client.stop.assert_awaited_once_with()
        client.start.assert_awaited_once_with()


    async def test_restart_after_reauth_starts_unloaded_client_with_fresh_token(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._command_lock = asyncio.Lock()
        client._token = "stale-token"
        client._runner = None
        client.stop = AsyncMock()
        client.start = AsyncMock()

        await DHEClient.restart_after_reauth(client)

        self.assertIsNone(client._token)
        client.stop.assert_not_awaited()
        client.start.assert_awaited_once_with()


    async def test_client_init_normalizes_host_and_url(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        client_module.async_get_clientsession = Mock(return_value=object())

        class _FakeConfig:
            def path(self, value: str) -> str:
                return f"/config/{value}"

        class _FakeHass:
            config = _FakeConfig()

        client = DHEClient(
            _FakeHass(),
            " http://[2001:db8::1]/ ",
            8443,
            ".storage/token.txt",
            "DHE",
        )

        self.assertEqual(client.host, "2001:db8::1")
        self.assertEqual(client._url_host, "[2001:db8::1]")
        self.assertEqual(client.base_url, "http://[2001:db8::1]:8443")
        self.assertEqual(client.token_path, "/config/.storage/token.txt")


    async def test_stop_cancels_runner_and_reconnect_grace_task(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        runner_task = asyncio.create_task(asyncio.sleep(60))
        grace_task = asyncio.create_task(asyncio.sleep(60))
        client = DHEClient.__new__(DHEClient)
        client._stopped = client_module.asyncio.Event()
        client._runner = runner_task
        client._ctx = None
        client._ready = client_module.asyncio.Event()
        client._ready.set()
        client._online = True
        client._available = True
        client._online_callbacks = set()
        client._availability_callbacks = set()
        client._diagnostic_callbacks = set()
        client._diagnostic_state = {}
        client._diagnostic_callbacks = set()
        client._last_message_monotonic = None
        client._notify_callbacks = Mock()
        client._reconnect_grace_task = grace_task
        client._pending_setpoint_future = None
        client._pending_write_future = None

        await DHEClient.stop(client)

        self.assertTrue(runner_task.cancelled())
        self.assertTrue(grace_task.cancelled())
        self.assertIsNone(client._runner)
        self.assertIsNone(client._reconnect_grace_task)
        self.assertFalse(client._ready.is_set())
        self.assertFalse(client._online)
        self.assertFalse(client._available)
        self.assertEqual(client._diagnostic_state["connection_state"], "stopped")


    async def test_failed_runtime_and_stop_release_all_session_state(self) -> None:
        module = _load_client()
        module.async_get_clientsession = Mock(return_value=object())
        client = module.DHEClient(types.SimpleNamespace(), "example.invalid", 8443, None, "Test")
        ctx = module.DHESession("synthetic-session", "synthetic-token")
        client._open_authenticated_session = AsyncMock(return_value=ctx)
        client._request_initial_values = AsyncMock()
        client._wait_for_initial_runtime_values = AsyncMock()
        client._read_events_once = AsyncMock(side_effect=AssertionError("unexpected bug"))
        client._close_session = AsyncMock()
        pending = client._pending_setpoint_future = asyncio.get_running_loop().create_future()
        client._runner = asyncio.create_task(client._run_loop())
        with self.assertRaisesRegex(AssertionError, "unexpected bug"):
            await client._runner
        self.assertIsNone(client._ctx)
        self.assertFalse(client._ready.is_set())
        self.assertFalse(client.available)
        self.assertFalse(client.online)
        self.assertTrue(pending.cancelled())
        await client.stop()
        client._close_session.assert_awaited_once_with(ctx)
        self.assertIsNone(client._runner)


    async def test_open_session_uses_structured_open_payload(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._get_text = AsyncMock(
            return_value=(
                '0{"sid":"polling sid","websocketSid":"websocket sid",'
                '"pingInterval":15000}'
            )
        )
        client._post_packet = AsyncMock(return_value="")
        client._poll_url = Mock(return_value="http://example.invalid/socket.io")

        ctx = await DHEClient._open_session(client, "token value")

        self.assertEqual(ctx.sid, "polling sid")
        self.assertEqual(ctx.websocket_sid, "websocket sid")
        self.assertEqual(ctx.url_token, "token value")
        self.assertEqual(ctx.ping_interval, 15.0)
        client._post_packet.assert_awaited_once_with(ctx, f"40/{protocol_module.NS}")


    def test_parse_socketio_events_continues_after_malformed_frame(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        client = DHEClient.__new__(DHEClient)

        events = DHEClient._parse_socketio_events(
            client,
            [
                (
                    '42/1.0.0,["message",{"text":"bad",}]'
                    '42/1.0.0,["message",{"command":"ok","value":1}]'
                ),
            ],
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].name, "message")
        self.assertEqual(events[0].data, {"command": "ok", "value": 1})


    async def test_websocket_upgrade_leaves_control_ping_handling_enabled(self) -> None:
        client_module = _load_client()
        transport_module = _load_component_module("client_transport")
        DHEClient = client_module.DHEClient
        DHESession = client_module.DHESession

        message = types.SimpleNamespace(
            type=transport_module.aiohttp.WSMsgType.TEXT,
            data="3probe",
        )

        class _FakeWebSocket:
            closed = False

            def __init__(self) -> None:
                self.send_str = AsyncMock()
                self.close = AsyncMock()
                self.receive = AsyncMock(return_value=message)

        websocket = _FakeWebSocket()
        session = types.SimpleNamespace(ws_connect=AsyncMock(return_value=websocket))
        client = DHEClient.__new__(DHEClient)
        client._session = session
        client._connect_websocket = session.ws_connect
        client._send_lock = client_module.asyncio.Lock()
        client._websocket_url_candidates = Mock(
            return_value=(("websocket-sid", "socket-sid", "ws://example.invalid/ws"),)
        )
        client._websocket_headers = Mock(
            return_value={"Origin": "http://example.invalid"}
        )

        def _capture_background_task(coro, _name):
            coro.close()
            return object()

        client._create_background_task = Mock(side_effect=_capture_background_task)

        ctx = DHESession(url_token="token", sid="sid")

        await DHEClient._upgrade_to_websocket(client, ctx)

        self.assertIs(ctx.websocket, websocket)
        self.assertIsNotNone(ctx.websocket_ping_task)
        session.ws_connect.assert_awaited_once()
        session.ws_connect.assert_awaited_once_with("ws://example.invalid/ws", "socket-sid")
        websocket.send_str.assert_any_await("2probe")
        websocket.send_str.assert_any_await("5")


    async def test_websocket_upgrade_failure_updates_transport_metrics(self) -> None:
        client_module = _load_client()
        transport_module = _load_component_module("client_transport")
        DHEClient = client_module.DHEClient
        DHESession = client_module.DHESession

        session = types.SimpleNamespace(
            ws_connect=AsyncMock(
                side_effect=transport_module.aiohttp.ClientError("connect failed")
            )
        )
        client = DHEClient.__new__(DHEClient)
        client._session = session
        client._websocket_upgrade_failures = 0
        client._connect_websocket = session.ws_connect
        client._websocket_url_candidates = Mock(
            return_value=(("websocket-sid", "socket-sid", "ws://example.invalid/ws"),)
        )
        client._websocket_headers = Mock(
            return_value={"Origin": "http://example.invalid"}
        )
        ctx = DHESession(url_token="token", sid="sid")

        with self.assertRaisesRegex(client_module.DHEError, "ClientError"):
            await DHEClient._upgrade_to_websocket(client, ctx)

        self.assertEqual(client.transport_statistics["websocket_upgrade_failures"], 1)


    async def test_websocket_heartbeat_failure_forces_reconnect(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHESession = client_module.DHESession

        websocket = types.SimpleNamespace(closed=False)
        client = DHEClient.__new__(DHEClient)
        client._stopped = client_module.asyncio.Event()
        client._send_websocket_packet = AsyncMock(
            side_effect=RuntimeError("socket write failed")
        )
        client._force_reconnect = AsyncMock()
        ctx = DHESession(
            url_token="token",
            sid="sid",
            websocket=websocket,
            ping_interval=0,
        )

        await DHEClient._websocket_ping_loop(client, ctx)

        client._send_websocket_packet.assert_awaited_once_with(ctx, "2")
        client._force_reconnect.assert_awaited_once()
        args, kwargs = client._force_reconnect.await_args
        self.assertEqual(args, (ctx,))
        self.assertNotIn("immediate_availability", kwargs)
        self.assertEqual(
            kwargs["reason"],
            "Heartbeat failed: RuntimeError: socket write failed",
        )


    async def test_websocket_idle_timeout_returns_closed_event(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHESession = client_module.DHESession
        transport_module = sys.modules[f"{PACKAGE_NAME}.client_transport"]
        original_min_timeout = transport_module.WEBSOCKET_IDLE_TIMEOUT_MIN
        transport_module.WEBSOCKET_IDLE_TIMEOUT_MIN = 0.1

        class _IdleWebSocket:
            closed = False

            async def receive(self):
                await asyncio.sleep(1)

        client = DHEClient.__new__(DHEClient)
        ctx = DHESession(
            url_token="token",
            sid="sid",
            websocket=_IdleWebSocket(),
            ping_interval=0.01,
        )

        try:
            events = await DHEClient._read_websocket_events_once(client, ctx)
        finally:
            transport_module.WEBSOCKET_IDLE_TIMEOUT_MIN = original_min_timeout

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].name, "__closed")
        self.assertEqual(events[0].data, "DHE websocket idle timeout after 0.1s")


    async def test_stale_runtime_watchdog_sends_probe_before_forced_reconnect(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHESession = client_module.DHESession

        client = DHEClient.__new__(DHEClient)
        ctx = DHESession(url_token="token", sid="sid")
        client._ctx = ctx
        client._stopped = client_module.asyncio.Event()
        client._ready = client_module.asyncio.Event()
        client._ready.set()
        client._message_count = 12
        client._last_message_monotonic = 0.0
        client._stale_watchdog_probe_message_count = None
        client._stale_watchdog_probe_started_monotonic = None
        client._request_odb_value = AsyncMock()
        client._force_reconnect = AsyncMock()

        original_monotonic = client_module.time.monotonic
        client_module.time.monotonic = lambda: 901.0
        try:
            await DHEClient._maybe_recover_stale_runtime(client, ctx)
        finally:
            client_module.time.monotonic = original_monotonic

        client._request_odb_value.assert_awaited_once_with(
            ctx,
            client_module.ID_DEVICE_STATUS,
        )
        client._force_reconnect.assert_not_awaited()
        self.assertEqual(client._stale_watchdog_probe_message_count, 12)
        self.assertEqual(client._stale_watchdog_probe_started_monotonic, 901.0)


    async def test_stale_runtime_watchdog_skips_probe_state_after_context_change(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHESession = client_module.DHESession

        client = DHEClient.__new__(DHEClient)
        ctx = DHESession(url_token="token", sid="sid")
        client._ctx = ctx
        client._stopped = client_module.asyncio.Event()
        client._ready = client_module.asyncio.Event()
        client._ready.set()
        client._message_count = 12
        client._last_message_monotonic = 0.0
        client._stale_watchdog_probe_message_count = None
        client._stale_watchdog_probe_started_monotonic = None
        client._force_reconnect = AsyncMock()

        async def _replace_context(_ctx, _odb_id):
            client._ctx = None

        client._request_odb_value = AsyncMock(side_effect=_replace_context)

        original_monotonic = client_module.time.monotonic
        client_module.time.monotonic = lambda: 901.0
        try:
            await DHEClient._maybe_recover_stale_runtime(client, ctx)
        finally:
            client_module.time.monotonic = original_monotonic

        client._request_odb_value.assert_awaited_once_with(
            ctx,
            client_module.ID_DEVICE_STATUS,
        )
        client._force_reconnect.assert_not_awaited()
        self.assertIsNone(client._stale_watchdog_probe_message_count)
        self.assertIsNone(client._stale_watchdog_probe_started_monotonic)


    async def test_stale_runtime_watchdog_reconnects_when_probe_stays_unanswered(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHESession = client_module.DHESession
        constants = _load_component_module("client_constants")

        client = DHEClient.__new__(DHEClient)
        ctx = DHESession(url_token="token", sid="sid")
        client._ctx = ctx
        client._stopped = client_module.asyncio.Event()
        client._ready = client_module.asyncio.Event()
        client._ready.set()
        client._message_count = 5
        client._last_message_monotonic = 0.0
        client._stale_watchdog_probe_message_count = 5
        client._stale_watchdog_probe_started_monotonic = 0.0
        client._request_odb_value = AsyncMock()
        client._force_reconnect = AsyncMock()

        original_monotonic = client_module.time.monotonic
        client_module.time.monotonic = lambda: (
            constants.RUNTIME_STALE_WATCHDOG_SECONDS
            + constants.RUNTIME_STALE_PROBE_GRACE_SECONDS
            + 1.0
        )
        try:
            await DHEClient._maybe_recover_stale_runtime(client, ctx)
        finally:
            client_module.time.monotonic = original_monotonic

        client._request_odb_value.assert_not_awaited()
        client._force_reconnect.assert_awaited_once()
        args, kwargs = client._force_reconnect.await_args
        self.assertEqual(args, (ctx,))
        self.assertIn("Runtime stale watchdog", kwargs["reason"])
        self.assertIsNone(client._stale_watchdog_probe_message_count)
        self.assertIsNone(client._stale_watchdog_probe_started_monotonic)


    async def test_stale_runtime_watchdog_clears_probe_after_new_message(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHESession = client_module.DHESession

        client = DHEClient.__new__(DHEClient)
        ctx = DHESession(url_token="token", sid="sid")
        client._ctx = ctx
        client._stopped = client_module.asyncio.Event()
        client._ready = client_module.asyncio.Event()
        client._ready.set()
        client._message_count = 9
        client._last_message_monotonic = 100.0
        client._stale_watchdog_probe_message_count = 8
        client._stale_watchdog_probe_started_monotonic = 50.0
        client._request_odb_value = AsyncMock()
        client._force_reconnect = AsyncMock()

        await DHEClient._maybe_recover_stale_runtime(client, ctx)

        client._request_odb_value.assert_not_awaited()
        client._force_reconnect.assert_not_awaited()
        self.assertIsNone(client._stale_watchdog_probe_message_count)
        self.assertIsNone(client._stale_watchdog_probe_started_monotonic)


    async def test_stale_runtime_watchdog_reconnects_when_probe_command_fails(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHESession = client_module.DHESession
        DHEError = client_module.DHEError

        client = DHEClient.__new__(DHEClient)
        ctx = DHESession(url_token="token", sid="sid")
        client._ctx = ctx
        client._stopped = client_module.asyncio.Event()
        client._ready = client_module.asyncio.Event()
        client._ready.set()
        client._message_count = 4
        client._last_message_monotonic = 0.0
        client._stale_watchdog_probe_message_count = None
        client._stale_watchdog_probe_started_monotonic = None
        client._request_odb_value = AsyncMock(side_effect=DHEError("transport closed"))
        client._force_reconnect = AsyncMock()

        original_monotonic = client_module.time.monotonic
        client_module.time.monotonic = lambda: 901.0
        try:
            await DHEClient._maybe_recover_stale_runtime(client, ctx)
        finally:
            client_module.time.monotonic = original_monotonic

        client._request_odb_value.assert_awaited_once()
        client._force_reconnect.assert_awaited_once()
        args, kwargs = client._force_reconnect.await_args
        self.assertEqual(args, (ctx,))
        self.assertIn("probe failed", kwargs["reason"])
        self.assertIsNone(client._stale_watchdog_probe_message_count)
        self.assertIsNone(client._stale_watchdog_probe_started_monotonic)


    async def test_force_reconnect_keeps_available_inside_reconnect_grace(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._ctx = None
        client._ready = client_module.asyncio.Event()
        client._ready.set()
        client._stopped = client_module.asyncio.Event()
        client._online = True
        client._available = True
        client._online_callbacks = set()
        client._availability_callbacks = set()
        client._diagnostic_callbacks = set()
        client._diagnostic_state = {}
        client._last_message_monotonic = None
        client._stale_watchdog_probe_message_count = 4
        client._stale_watchdog_probe_started_monotonic = 12.0
        client._notify_callbacks = Mock()
        client._reconnect_grace_task = None
        scheduled_tasks: list[tuple[object, str]] = []

        def _capture_background_task(coro, name):
            scheduled_tasks.append((coro, name))
            coro.close()
            return types.SimpleNamespace(done=lambda: False, cancel=Mock())

        client._create_background_task = Mock(side_effect=_capture_background_task)
        client._connection_supervisor = client_module.DHEConnectionSupervisor(
            base_delay=2.0,
            max_delay=10.0,
            grace_period=15.0,
            monotonic=lambda: 0.0,
        )

        await DHEClient._force_reconnect(client, reason="test reconnect")

        self.assertFalse(client._ready.is_set())
        self.assertIsNone(client._stale_watchdog_probe_message_count)
        self.assertIsNone(client._stale_watchdog_probe_started_monotonic)
        self.assertFalse(client._online)
        self.assertTrue(client._available)
        self.assertEqual(client._diagnostic_state["connection_state"], "reconnecting")
        self.assertEqual(
            client._diagnostic_state["last_reconnect_reason"], "test reconnect"
        )
        self.assertEqual(client._diagnostic_state["next_reconnect_delay_seconds"], 2.0)
        self.assertEqual(
            scheduled_tasks[0][1],
            "stiebel_dhe_connect_reconnect_grace_expiry",
        )


    async def test_force_reconnect_marks_unavailable_after_reconnect_grace(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        now = 0.0

        client = DHEClient.__new__(DHEClient)
        client._ctx = None
        client._ready = client_module.asyncio.Event()
        client._ready.set()
        client._stopped = client_module.asyncio.Event()
        client._online = True
        client._available = True
        client._online_callbacks = set()
        client._availability_callbacks = set()
        client._diagnostic_callbacks = set()
        client._diagnostic_state = {}
        client._last_message_monotonic = None
        client._notify_callbacks = Mock()
        client._reconnect_grace_task = None
        scheduled_task = types.SimpleNamespace(done=lambda: False, cancel=Mock())

        def _capture_background_task(coro, _name):
            coro.close()
            return scheduled_task

        client._create_background_task = Mock(side_effect=_capture_background_task)
        client._connection_supervisor = client_module.DHEConnectionSupervisor(
            base_delay=2.0,
            max_delay=10.0,
            grace_period=15.0,
            monotonic=lambda: now,
        )

        await DHEClient._force_reconnect(client, reason="first reconnect")
        self.assertTrue(client._available)

        now = 16.0
        client._online = True
        client._ready.set()
        await DHEClient._force_reconnect(client, reason="second reconnect")

        self.assertFalse(client._available)
        scheduled_task.cancel.assert_called_once()
        self.assertEqual(client._diagnostic_state["connection_state"], "reconnecting")
        self.assertEqual(
            client._diagnostic_state["last_reconnect_reason"], "second reconnect"
        )
        self.assertEqual(client._diagnostic_state["next_reconnect_delay_seconds"], 4.0)


    async def test_reconnect_grace_timer_marks_unavailable_when_expired(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        now = 0.0

        diagnostic_callback = Mock()
        client = DHEClient.__new__(DHEClient)
        client._ctx = None
        client._ready = client_module.asyncio.Event()
        client._stopped = client_module.asyncio.Event()
        client._available = True
        client._availability_callbacks = set()
        client._diagnostic_callbacks = {diagnostic_callback}
        client._copy_diagnostic_state = Mock(
            return_value={"connection_state": "reconnecting"}
        )
        client._notify_callbacks = Mock()
        client._reconnect_grace_task = object()
        client._connection_supervisor = client_module.DHEConnectionSupervisor(
            grace_period=15.0,
            monotonic=lambda: now,
        )
        client._connection_supervisor.mark_disconnected()

        now = 15.1
        client._reconnect_grace_task = client_module.asyncio.current_task()
        await DHEClient._expire_reconnect_grace_after(client, 0)

        self.assertFalse(client._available)
        self.assertIsNone(client._reconnect_grace_task)
        self.assertTrue(
            any(
                call.args and call.args[0] == "diagnostic"
                for call in client._notify_callbacks.call_args_list
            )
        )


    async def test_reconnect_grace_timer_preserves_ready_or_stopped_client(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        for ready, stopped in ((True, False), (False, True)):
            with self.subTest(ready=ready, stopped=stopped):
                monotonic = Mock(return_value=0.0)
                client = DHEClient.__new__(DHEClient)
                client._ctx = object()
                client._ready = asyncio.Event()
                client._stopped = asyncio.Event()
                if ready:
                    client._ready.set()
                if stopped:
                    client._stopped.set()
                client._available = True
                client._availability_callbacks = set()
                client._notify_callbacks = Mock()
                client._connection_supervisor = client_module.DHEConnectionSupervisor(
                    grace_period=15.0,
                    monotonic=monotonic,
                )
                client._connection_supervisor.mark_disconnected()
                monotonic.return_value = 15.0
                client._reconnect_grace_task = asyncio.current_task()

                await client._expire_reconnect_grace_after(0)

                self.assertTrue(client.available)
                client._notify_callbacks.assert_not_called()
                self.assertIsNone(client._reconnect_grace_task)


    async def test_stale_reconnect_grace_timer_does_not_clear_new_timer(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        now = 15.1
        new_task = object()

        client = DHEClient.__new__(DHEClient)
        client._ctx = None
        client._ready = client_module.asyncio.Event()
        client._stopped = client_module.asyncio.Event()
        client._available = True
        client._availability_callbacks = set()
        client._notify_callbacks = Mock()
        client._reconnect_grace_task = new_task
        client._connection_supervisor = client_module.DHEConnectionSupervisor(
            grace_period=15.0,
            monotonic=lambda: now,
        )
        client._connection_supervisor.mark_disconnected()

        await DHEClient._expire_reconnect_grace_after(client, 0)

        self.assertIs(client._reconnect_grace_task, new_task)


    async def test_websocket_heartbeat_does_not_hide_programming_runtime_errors(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHESession = client_module.DHESession

        websocket = types.SimpleNamespace(closed=False)
        client = DHEClient.__new__(DHEClient)
        client._stopped = client_module.asyncio.Event()
        client._send_websocket_packet = AsyncMock(
            side_effect=RuntimeError("unexpected invalid state")
        )
        client._force_reconnect = AsyncMock()
        ctx = DHESession(
            url_token="token",
            sid="sid",
            websocket=websocket,
            ping_interval=0,
        )

        with self.assertRaisesRegex(RuntimeError, "unexpected invalid state"):
            await DHEClient._websocket_ping_loop(client, ctx)

        client._send_websocket_packet.assert_awaited_once_with(ctx, "2")
        client._force_reconnect.assert_not_awaited()
