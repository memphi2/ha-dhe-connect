"""Tests for sanitized protocol replay fixtures."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
import unittest
from unittest.mock import Mock

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

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "dhe_protocol_replay_sanitized.json"


def _load_fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _fixture_packets(fixture: dict[str, object]) -> list[str]:
    packets = fixture["socketio_packets"]
    assert isinstance(packets, list)
    return [str(item["packet"]) for item in packets if isinstance(item, dict)]


def _length_prefixed_payload(packets: list[str]) -> str:
    return "".join(f"{len(packet)}:{packet}" for packet in packets)


class TestSanitizedProtocolReplayFixtures(unittest.IsolatedAsyncioTestCase):
    """Replay sanitized DHE frames through parser and runtime handlers."""

    def test_fixture_contains_no_live_identifiers_or_credentials(self) -> None:
        text = FIXTURE_PATH.read_text(encoding="utf-8")

        self.assertNotRegex(text, re.compile(r"\b(?:10|172|192)\.\d+\.\d+\.\d+\b"))
        self.assertNotRegex(text, re.compile(r"\b[A-Za-z0-9_-]{32,}\b"))
        self.assertNotIn("homeassistant", text.lower())
        self.assertNotIn("password", text.lower())
        self.assertNotIn("token", text.lower())

    def test_fixture_open_payload_and_packets_parse(self) -> None:
        client_module = _load_client()
        engineio_helpers = _load_component_module("engineio_helpers")
        DHEClient = client_module.DHEClient
        fixture = _load_fixture()
        packets = _fixture_packets(fixture)

        open_payload = engineio_helpers.parse_engineio_open_payload(
            str(fixture["engineio_open"])
        )
        decoded_packets = engineio_helpers.decode_engineio_payload(
            _length_prefixed_payload(packets)
        )
        events = DHEClient._parse_socketio_events(
            DHEClient.__new__(DHEClient),
            decoded_packets,
        )

        self.assertEqual(open_payload["sid"], "fixture-polling-sid")
        self.assertEqual(open_payload["websocketSid"], "fixture-websocket-sid")
        self.assertEqual(len(decoded_packets), len(packets))
        self.assertEqual(len(events), len(packets))
        self.assertTrue(all(event.name == "message" for event in events))

    async def test_fixture_replays_into_runtime_state(self) -> None:
        client_module = _load_client()
        engineio_helpers = _load_component_module("engineio_helpers")
        protocol = _load_protocol()
        DHEClient = client_module.DHEClient
        client_module.async_get_clientsession = Mock(return_value=object())
        client = DHEClient(
            _FakeHass(asyncio.get_running_loop()),
            "fixture.invalid",
            8443,
            ".storage/replay-fixture",
            "DHE",
        )
        fixture = _load_fixture()
        events = DHEClient._parse_socketio_events(
            client,
            engineio_helpers.decode_engineio_payload(
                _length_prefixed_payload(_fixture_packets(fixture))
            ),
        )

        for event in events:
            await DHEClient._handle_runtime_event(client, event)

        self.assertEqual(client.last_setpoint, 41.5)
        self.assertEqual(
            client.last_measurements[protocol.ID_DEVICE_STATUS],
            "status_2",
        )
        self.assertEqual(client.last_radio_state["station"]["Name"], "Example FM")
        self.assertTrue(client.last_radio_state["play"])
        self.assertEqual(client.last_radio_state["favorites"][0]["Id"], 4301)
        self.assertEqual(
            client.last_weather_state["location"]["LocationId"],
            "fixture-location",
        )
        self.assertEqual(
            client.last_measurements[protocol.ID_SAVING_MONITOR_POSSIBLE_WATER],
            42.5,
        )
        self.assertEqual(
            client.last_measurements[protocol.ID_SAVING_MONITOR_POSSIBLE_ENERGY],
            1.2,
        )


class _FakeConfig:
    def path(self, value: str) -> str:
        return f"/tmp/{value}"


class _FakeHass:
    config = _FakeConfig()

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
