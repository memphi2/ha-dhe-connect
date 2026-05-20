"""Tests for sanitized protocol replay fixtures."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import Mock
from typing import Any

try:
    from tests.test_client_weather_favorites import (
        _load_client,
        _load_component_module,
    )
except ModuleNotFoundError:
    from test_client_weather_favorites import (
        _load_client,
        _load_component_module,
    )

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures"
REPLAY_FIXTURE_NAME = "dhe_protocol_replay_sanitized.json"
EXPECTED_FIRMWARE_PROFILES = ("firmware_a", "firmware_b", "firmware_c")


def _fixture_paths() -> list[Path]:
    return sorted(FIXTURE_ROOT.glob(f"firmware_*/{REPLAY_FIXTURE_NAME}"))


def _load_fixture(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture_packets(fixture: dict[str, object]) -> list[str]:
    packets = fixture["socketio_packets"]
    assert isinstance(packets, list)
    return [str(item["packet"]) for item in packets if isinstance(item, dict)]


def _length_prefixed_payload(packets: list[str]) -> str:
    return "".join(f"{len(packet)}:{packet}" for packet in packets)


def _dotted_value(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, dict):
            current = current[part]
            continue
        if isinstance(current, list):
            current = current[int(part)]
            continue
        raise KeyError(path)
    return current


def _assert_expected_values(
    testcase: unittest.TestCase,
    actual: Any,
    expected: dict[str, Any],
) -> None:
    for dotted_path, expected_value in expected.items():
        actual_value = _dotted_value(actual, dotted_path)
        if isinstance(expected_value, float):
            testcase.assertAlmostEqual(actual_value, expected_value)
        else:
            testcase.assertEqual(actual_value, expected_value)


class TestSanitizedProtocolReplayFixtures(unittest.IsolatedAsyncioTestCase):
    """Replay sanitized DHE frames through parser and runtime handlers."""

    def test_fixture_inventory_is_firmware_scoped(self) -> None:
        paths = _fixture_paths()
        self.assertEqual(
            [path.parent.name for path in paths],
            list(EXPECTED_FIRMWARE_PROFILES),
        )
        for path in paths:
            fixture = _load_fixture(path)
            self.assertEqual(fixture["version"], 2)
            self.assertEqual(fixture["firmware_profile"], path.parent.name)

    def test_fixture_contains_no_live_identifiers_or_credentials(self) -> None:
        for path in _fixture_paths():
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")

                self.assertNotRegex(
                    text, re.compile(r"\b(?:10|172|192)\.\d+\.\d+\.\d+\b")
                )
                self.assertNotRegex(
                    text,
                    re.compile(r"\b[0-9a-f]{2}(:[0-9a-f]{2}){5}\b", re.I),
                )
                self.assertNotRegex(text, re.compile(r"\b[A-Za-z0-9_-]{32,}\b"))
                self.assertNotIn("homeassistant", text.lower())
                self.assertNotIn("password", text.lower())
                self.assertNotIn("token", text.lower())

    def test_fixture_open_payload_and_packets_parse(self) -> None:
        client_module = _load_client()
        engineio_helpers = _load_component_module("engineio_helpers")
        DHEClient = client_module.DHEClient

        for path in _fixture_paths():
            with self.subTest(path=path):
                fixture = _load_fixture(path)
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

                self.assertEqual(open_payload["pingInterval"], 25000)
                self.assertEqual(len(decoded_packets), len(packets))
                self.assertEqual(len(events), len(packets))
                self.assertTrue(all(event.name == "message" for event in events))

    async def test_fixture_replays_into_runtime_state(self) -> None:
        client_module = _load_client()
        engineio_helpers = _load_component_module("engineio_helpers")
        DHEClient = client_module.DHEClient
        client_module.async_get_clientsession = Mock(return_value=object())

        for path in _fixture_paths():
            with self.subTest(path=path):
                client = DHEClient(
                    _FakeHass(asyncio.get_running_loop()),
                    "fixture.invalid",
                    8443,
                    f".storage/replay-fixture-{path.parent.name}",
                    "DHE",
                )
                fixture = _load_fixture(path)
                events = DHEClient._parse_socketio_events(
                    client,
                    engineio_helpers.decode_engineio_payload(
                        _length_prefixed_payload(_fixture_packets(fixture))
                    ),
                )

                for event in events:
                    await DHEClient._handle_runtime_event(client, event)

                expected = fixture["expected_runtime_state"]
                assert isinstance(expected, dict)
                self._assert_expected_runtime_state(client, expected)

    def _assert_expected_runtime_state(
        self,
        client: Any,
        expected: dict[str, Any],
    ) -> None:
        if "setpoint" in expected:
            self.assertEqual(client.last_setpoint, expected["setpoint"])

        measurements = expected.get("measurements", {})
        assert isinstance(measurements, dict)
        for measurement_id, expected_value in measurements.items():
            actual_value = client.last_measurements[int(measurement_id)]
            if isinstance(expected_value, float):
                self.assertAlmostEqual(actual_value, expected_value)
            else:
                self.assertEqual(actual_value, expected_value)

        measurement_attributes = expected.get("measurement_attributes", {})
        assert isinstance(measurement_attributes, dict)
        for measurement_id, expected_values in measurement_attributes.items():
            assert isinstance(expected_values, dict)
            attributes = client._last_measurement_attributes[int(measurement_id)]
            _assert_expected_values(self, attributes, expected_values)

        radio = expected.get("radio", {})
        assert isinstance(radio, dict)
        _assert_expected_values(self, client.last_radio_state, radio)

        radio_internal = expected.get("radio_internal", {})
        assert isinstance(radio_internal, dict)
        _assert_expected_values(
            self,
            {
                "catalogs": client._last_radio_catalogs,
                "stations": client._last_radio_stations,
            },
            radio_internal,
        )

        weather = expected.get("weather", {})
        assert isinstance(weather, dict)
        _assert_expected_values(self, client.last_weather_state, weather)

        weather_internal = expected.get("weather_internal", {})
        assert isinstance(weather_internal, dict)
        _assert_expected_values(
            self,
            {"countries": client._last_weather_countries},
            weather_internal,
        )

        runtime_parser_stats = expected.get("runtime_parser_stats", {})
        assert isinstance(runtime_parser_stats, dict)
        for category, expected_count in runtime_parser_stats.items():
            self.assertEqual(client._runtime_parser_stats[category], expected_count)


class _FakeConfig:
    def path(self, value: str) -> str:
        return str(Path(tempfile.gettempdir()) / value)


class _FakeHass:
    config = _FakeConfig()

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
