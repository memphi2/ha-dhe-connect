"""Tests for pure Engine.IO frame helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "custom_components" / "stiebel_dhe_connect" / "engineio_helpers.py"


def _load_engineio_helpers():
    spec = importlib.util.spec_from_file_location("engineio_helpers", HELPERS)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestEngineIOHelpers(unittest.TestCase):
    """Validate Engine.IO payload helpers."""

    def setUp(self) -> None:
        self.helpers = _load_engineio_helpers()

    def test_open_payload_parser_accepts_raw_open_packet(self) -> None:
        payload = (
            '0{"sid":"polling sid","websocketSid":"websocket sid",'
            '"pingInterval":25000}'
        )

        parsed = self.helpers.parse_engineio_open_payload(payload)

        self.assertEqual(parsed["sid"], "polling sid")
        self.assertEqual(parsed["websocketSid"], "websocket sid")
        self.assertEqual(
            self.helpers.engineio_ping_interval(parsed, default_interval=1.0),
            25.0,
        )

    def test_open_payload_parser_accepts_length_prefixed_packet(self) -> None:
        packet = '0{"sid":"sid-1","pingInterval":"30000"}'
        parsed = self.helpers.parse_engineio_open_payload(f"{len(packet)}:{packet}")

        self.assertEqual(parsed["sid"], "sid-1")
        self.assertEqual(
            self.helpers.engineio_ping_interval(parsed, default_interval=1.0),
            30.0,
        )

    def test_open_payload_parser_rejects_malformed_json(self) -> None:
        with self.assertRaisesRegex(ValueError, "Could not parse DHE open payload"):
            self.helpers.parse_engineio_open_payload('0{"sid":')

    def test_decode_engineio_payload_splits_length_prefixed_packets(self) -> None:
        first = '42/1.0.0,["message",{"value":1}]'
        second = '42/1.0.0,["message",{"value":2}]'
        payload = f"{len(first)}:{first}{len(second)}:{second}"

        self.assertEqual(
            self.helpers.decode_engineio_payload(payload),
            [first, second],
        )

    def test_balanced_json_array_keeps_nested_strings_intact(self) -> None:
        packet = (
            '42/1.0.0,["message",{"text":"keep ] and \\\\\\" quoted",'
            '"items":[1,2]}]tail'
        )

        json_text, next_pos = self.helpers.balanced_json_array(packet, 0)

        self.assertEqual(
            json_text,
            '["message",{"text":"keep ] and \\\\\\" quoted","items":[1,2]}]',
        )
        self.assertEqual(packet[next_pos:], "tail")

    def test_balanced_json_array_returns_malformed_but_balanced_array(self) -> None:
        packet = '42/1.0.0,["message",{"text":"bad",}]42/1.0.0,["message",{}]'

        json_text, next_pos = self.helpers.balanced_json_array(packet, 0)

        self.assertEqual(json_text, '["message",{"text":"bad",}]')
        self.assertEqual(packet[next_pos:], '42/1.0.0,["message",{}]')

    def test_ping_interval_falls_back_for_missing_or_invalid_values(self) -> None:
        self.assertEqual(
            self.helpers.engineio_ping_interval({}, default_interval=25.0),
            25.0,
        )
        self.assertEqual(
            self.helpers.engineio_ping_interval(
                {"pingInterval": "bad"},
                default_interval=25.0,
            ),
            25.0,
        )
