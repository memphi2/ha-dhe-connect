"""Tests for DHE client diagnostic summary helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTICS = (
    ROOT / "custom_components" / "stiebel_dhe_connect" / "client_diagnostics.py"
)


def _load_client_diagnostics():
    spec = importlib.util.spec_from_file_location("client_diagnostics", DIAGNOSTICS)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestClientDiagnostics(unittest.TestCase):
    """Validate compact payload summaries used by client diagnostics."""

    def setUp(self) -> None:
        self.diagnostics = _load_client_diagnostics()

    def test_radio_summary_keeps_identifying_station_fields(self) -> None:
        summary = self.diagnostics.summarize_radio_value([
            {"Id": 1, "Name": "Radio One", "City": "Essen", "StreamUrls": ["x"]},
            {"Id": 2, "Name": "Radio Two", "City": "Dusseldorf"},
        ])

        self.assertEqual(
            summary,
            {
                "count": 2,
                "stations": [
                    {"Id": 1, "Name": "Radio One", "City": "Essen"},
                    {"Id": 2, "Name": "Radio Two", "City": "Dusseldorf"},
                ],
            },
        )

    def test_weather_summary_keeps_location_and_forecast_dates(self) -> None:
        summary = self.diagnostics.summarize_weather_value({
            "Location": {"Name": "Essen", "Country": "DE", "LocationId": "id-1"},
            "CompleteDays": [{"date": "2026-05-17"}, {"date": "2026-05-18"}],
            "SimpleDays": [{"date": "2026-05-19"}],
        })

        self.assertEqual(summary["location"]["Name"], "Essen")
        self.assertEqual(
            summary["completeDays"],
            {"count": 2, "dates": ["2026-05-17", "2026-05-18"]},
        )
        self.assertEqual(summary["simpleDays"], {"count": 1, "dates": ["2026-05-19"]})

    def test_diagnostic_summary_bounds_deep_payloads_and_long_strings(self) -> None:
        long_value = "x" * 130
        summary = self.diagnostics.summarize_diagnostic_value({
            "long": long_value,
            "nested": {"items": [{"deep": {"value": 1}}]},
        })

        self.assertEqual(summary["long"], f"{'x' * 117}...")
        self.assertEqual(
            summary["nested"],
            {"items": {"type": "list", "count": 1, "sample": ["dict"]}},
        )

    def test_diagnostic_error_is_short_and_includes_type(self) -> None:
        message = self.diagnostics.diagnostic_error(ValueError("bad value"))

        self.assertEqual(message, "ValueError: bad value")

    def test_diagnostic_error_redacts_auth_context(self) -> None:
        private_host = ".".join(("172", "16", "1", "147"))
        private_ten_host = ".".join(("10", "0", "0", "1"))
        local_host = "dhe-ja06.local"
        mac_address = "aa:bb:cc:dd:ee:ff"
        message = self.diagnostics.diagnostic_error(
            RuntimeError(
                "GET failed for "
                f"http://user:secret@{private_host}:8123/socket.io/?token=abc123 "
                f"fallback=http://{private_ten_host}:8123 "
                f"raw_host={private_ten_host}:8123 "
                f"mdns={local_host}:8443 "
                f"wlan_mac={mac_address} "
                "access_token=def456 Authorization: Bearer ghijk password=secret"
            )
        )

        self.assertIn("<redacted>", message)
        self.assertIn("<host>", message)
        self.assertIn("<private-host>", message)
        self.assertIn("<local-host>", message)
        self.assertIn("<mac-address>", message)
        self.assertNotIn("abc123", message)
        self.assertNotIn("def456", message)
        self.assertNotIn("ghijk", message)
        self.assertNotIn("secret", message)
        self.assertNotIn(private_host, message)
        self.assertNotIn(private_ten_host, message)
        self.assertNotIn(local_host, message)
        self.assertNotIn(mac_address, message)
        self.assertNotIn(".1", message)

    def test_redaction_preserves_ordinary_text(self) -> None:
        message = self.diagnostics.diagnostic_error(
            RuntimeError("code blue station and password reset forecast")
        )
        radio = self.diagnostics.summarize_radio_value([
            {"Id": 1, "Name": "Code Blue FM", "City": "Password Reset"},
        ])
        weather = self.diagnostics.summarize_weather_value({
            "Location": {"Name": "Code Blue", "Country": "Password Reset"},
        })

        self.assertEqual(
            message,
            "RuntimeError: code blue station and password reset forecast",
        )
        self.assertEqual(radio["stations"][0]["Name"], "Code Blue FM")
        self.assertEqual(radio["stations"][0]["City"], "Password Reset")
        self.assertEqual(weather["location"]["Name"], "Code Blue")
        self.assertEqual(weather["location"]["Country"], "Password Reset")

    def test_diagnostic_summary_redacts_sensitive_strings_and_keys(self) -> None:
        private_host = ".".join(("172", "16", "1", "147"))
        summary = self.diagnostics.summarize_diagnostic_value({
            "token=abc123": "Authorization: Bearer ghijk",
            "url": f"http://user:secret@{private_host}:8123/?token=abc123",
        })

        self.assertIn("token=<redacted>", summary)
        self.assertEqual(summary["token=<redacted>"], "<redacted>")
        self.assertIn("<host>", summary["url"])
        self.assertNotIn("abc123", str(summary))
        self.assertNotIn("ghijk", str(summary))
        self.assertNotIn("secret", str(summary))
        self.assertNotIn(private_host, str(summary))

        nested = self.diagnostics.summarize_diagnostic_value({
            "token": "should-hide-me",
            "code": "should-hide-code",
            "nested": {"access_token": "nest"},
        })
        self.assertEqual(nested["token"], "<redacted>")
        self.assertEqual(nested["code"], "<redacted>")
        self.assertEqual(nested["nested"]["access_token"], "<redacted>")

        mixed_case = self.diagnostics.summarize_diagnostic_value({
            "pairingToken": "alpha",
            "pairing_token": "beta",
            "client-authorization": "gamma",
        })
        self.assertEqual(mixed_case["pairingToken"], "<redacted>")
        self.assertEqual(mixed_case["pairing_token"], "<redacted>")
        self.assertEqual(mixed_case["client-authorization"], "<redacted>")

    def test_redaction_removes_username_only_url_hosts(self) -> None:
        message = self.diagnostics.redact_diagnostic_text(
            "GET https://alice@example.internal.local/status?token=abc123"
        )

        self.assertEqual(message, "GET https://<host>/status?token=<redacted>")
        self.assertNotIn("alice", message)
        self.assertNotIn("example", message)
        self.assertNotIn("abc123", message)

    def test_redaction_removes_websocket_url_hosts_and_userinfo(self) -> None:
        private_host = ".".join(("172", "16", "2", "124"))
        message = self.diagnostics.redact_diagnostic_text(
            "WS "
            "wss://bob:secret@dhe-ja06.local:8443/socket.io/?token=abc123 "
            f"fallback=ws://alice@{private_host}:8443/socket.io/?code=def456"
        )

        self.assertEqual(
            message,
            "WS "
            "wss://<host>/socket.io/?token=<redacted> "
            "fallback=ws://<host>/socket.io/?code=<redacted>",
        )
        self.assertNotIn("bob", message)
        self.assertNotIn("alice", message)
        self.assertNotIn("secret", message)
        self.assertNotIn(private_host, message)
        self.assertNotIn("dhe-ja06", message)
        self.assertNotIn("abc123", message)
        self.assertNotIn("def456", message)

    def test_diagnostic_summary_preserves_colliding_redacted_keys(self) -> None:
        summary = self.diagnostics.summarize_diagnostic_value({
            "token=abc123": "first",
            "token=def456": "second",
        })

        self.assertEqual(
            summary,
            {
                "token=<redacted>": "<redacted>",
                "token=<redacted>#2": "<redacted>",
            },
        )


if __name__ == "__main__":
    unittest.main()
