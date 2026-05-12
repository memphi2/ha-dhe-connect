"""Tests for DHE client protocol mapping helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT_MAPPING = (
    ROOT / "custom_components" / "stiebel_dhe_connect" / "client_mapping.py"
)


def _load_client_mapping():
    spec = importlib.util.spec_from_file_location("client_mapping", CLIENT_MAPPING)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestWeatherMapping(unittest.TestCase):
    """Validate weather payload normalization."""

    def setUp(self) -> None:
        self.mapping = _load_client_mapping()

    def test_normalize_weather_value_copies_location_and_days(self) -> None:
        raw = {
            "Location": {"Name": "Essen", "LocationId": "ID=1"},
            "CompleteDays": [{"date": "2026-05-10"}, "bad"],
            "SimpleDays": [{"date": "2026-05-11"}],
        }

        state = self.mapping.normalize_weather_value(raw)
        raw["Location"]["Name"] = "Changed"

        self.assertEqual(state["location"]["Name"], "Essen")
        self.assertEqual(state["complete_days"], [{"date": "2026-05-10"}])
        self.assertEqual(state["simple_days"], [{"date": "2026-05-11"}])

    def test_normalize_weather_locations_rejects_non_lists(self) -> None:
        self.assertIsNone(self.mapping.normalize_weather_locations_value({}))

    def test_normalize_weather_locations_keeps_only_dicts_and_copies(self) -> None:
        raw = [{"Name": "Essen"}, "bad", {"Name": "New York"}]

        locations = self.mapping.normalize_weather_locations_value(raw)
        raw[0]["Name"] = "Changed"

        self.assertEqual(locations, [{"Name": "Essen"}, {"Name": "New York"}])

    def test_weather_location_in_list_uses_location_id(self) -> None:
        self.assertTrue(
            self.mapping.weather_location_in_list(
                {"LocationId": "ID=1"},
                [{"LocationId": "ID=2"}, {"LocationId": "ID=1"}],
            )
        )
        self.assertFalse(
            self.mapping.weather_location_in_list({"Name": "Essen"}, [])
        )


class TestRadioMapping(unittest.TestCase):
    """Validate radio payload normalization."""

    def setUp(self) -> None:
        self.mapping = _load_client_mapping()

    def test_normalize_radio_stations_keeps_only_dicts_and_copies(self) -> None:
        raw = [{"Id": 1, "Name": "One"}, None, {"id": "2", "Name": "Two"}]

        stations = self.mapping.normalize_radio_stations_value(raw)
        raw[0]["Name"] = "Changed"

        self.assertEqual(
            stations,
            [{"Id": 1, "Name": "One"}, {"id": "2", "Name": "Two"}],
        )

    def test_normalize_radio_stations_rejects_non_lists(self) -> None:
        self.assertIsNone(self.mapping.normalize_radio_stations_value({}))

    def test_normalize_radio_string_catalog_trims_and_drops_empty_values(self) -> None:
        self.assertEqual(
            self.mapping.normalize_radio_string_catalog(["  Rock ", "", " Pop ", 123]),
            ["Rock", "Pop", "123"],
        )

    def test_radio_station_id_accepts_upper_and_lower_case_keys(self) -> None:
        self.assertEqual(self.mapping.radio_station_id({"Id": "4301"}), 4301)
        self.assertEqual(self.mapping.radio_station_id({"id": 3}), 3)
        self.assertIsNone(self.mapping.radio_station_id({"Id": "bad"}))

    def test_radio_station_in_list_uses_station_id(self) -> None:
        self.assertTrue(
            self.mapping.radio_station_in_list(3, [{"Id": 1}, {"Id": "3"}])
        )
        self.assertFalse(self.mapping.radio_station_in_list(4, [{"Id": 1}]))


if __name__ == "__main__":
    unittest.main()
