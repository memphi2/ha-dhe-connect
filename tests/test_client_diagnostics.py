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


if __name__ == "__main__":
    unittest.main()
