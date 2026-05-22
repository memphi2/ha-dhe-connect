"""Deterministic runtime replay edge-case tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

try:
    from tests.test_client_weather_favorites import _load_client, _load_component_module
except ModuleNotFoundError:
    from test_client_weather_favorites import _load_client, _load_component_module


class _FakeConfig:
    def path(self, value: str) -> str:
        return str(Path(tempfile.gettempdir()) / value)


class _FakeHass:
    config = _FakeConfig()

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop


class TestProtocolReplayEdgeCases(unittest.IsolatedAsyncioTestCase):
    """Replay malformed or partial runtime payloads without requiring hardware."""

    async def asyncSetUp(self) -> None:
        self.client_module = _load_client()
        self.protocol = _load_component_module("protocol")
        self.client_types = _load_component_module("client_types")
        self.client_module.async_get_clientsession = Mock(return_value=object())
        self.client = self.client_module.DHEClient(
            _FakeHass(asyncio.get_running_loop()),
            "fixture.invalid",
            8443,
            ".storage/replay-edge-cases",
            "DHE",
        )

    async def test_runtime_tolerates_malformed_message_payload(self) -> None:
        event = self.client_types.DHEEvent(name="message", data="bad-payload")

        await self.client_module.DHEClient._handle_runtime_event(self.client, event)

        stats = self.client.runtime_parser_statistics["counts"]
        self.assertEqual(stats.get("invalid_message_payload"), 1)

    async def test_runtime_tolerates_unknown_weather_payload_shape(self) -> None:
        event = self.client_types.DHEEvent(
            name="message",
            data={
                "command": self.protocol.WEATHER_FORECAST_SET_COMMAND,
                "value": "not-a-forecast-list",
            },
        )

        await self.client_module.DHEClient._handle_runtime_event(self.client, event)

        self.assertEqual(self.client.last_weather_state, {})
        stats = self.client.runtime_parser_statistics["counts"]
        self.assertEqual(stats.get("weather_state"), 1)

    async def test_runtime_tolerates_invalid_odb_payload_shape(self) -> None:
        event = self.client_types.DHEEvent(
            name="message",
            data={
                "command": self.protocol.ODB_GET_COMMAND,
                "value": 12,
            },
        )

        await self.client_module.DHEClient._handle_runtime_event(self.client, event)

        stats = self.client.runtime_parser_statistics["counts"]
        self.assertEqual(stats.get("invalid_odb_payload"), 1)

    async def test_runtime_closed_event_marks_reconnecting_and_raises(self) -> None:
        event = self.client_types.DHEEvent(name="__closed", data="Socket closed")

        with self.assertRaises(Exception) as ctx:
            await self.client_module.DHEClient._handle_runtime_event(self.client, event)
        self.assertEqual(type(ctx.exception).__name__, "DHESessionClosed")

        self.assertEqual(
            self.client.diagnostic_state.get("connection_state"),
            "reconnecting",
        )
        stats = self.client.runtime_parser_statistics["counts"]
        self.assertEqual(stats.get("socket_closed"), 1)
