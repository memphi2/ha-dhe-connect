"""Tests for config-flow mapping helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FLOW_MAPPING = (
    ROOT / "custom_components" / "stiebel_dhe_connect" / "config_flow_mapping.py"
)


def _load_config_flow_mapping():
    spec = importlib.util.spec_from_file_location(
        "config_flow_mapping",
        CONFIG_FLOW_MAPPING,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestConfigFlowWeatherMapping(unittest.TestCase):
    """Validate weather options mapping for flows."""

    def setUp(self) -> None:
        self.mapping = _load_config_flow_mapping()

    def test_weather_country_options_sort_and_skip_invalid_entries(self) -> None:
        self.assertEqual(
            self.mapping.weather_country_options(
                [
                    {"Country": "USA", "CountryId": 143},
                    {"Country": "", "CountryId": 1},
                    {"Country": "Deutschland", "CountryId": "34"},
                    {"Country": "Broken", "CountryId": "bad"},
                ]
            ),
            {
                "34": "Deutschland (34)",
                "143": "USA (143)",
            },
        )

    def test_default_weather_country_id_prefers_configured_country(self) -> None:
        self.assertEqual(
            self.mapping.default_weather_country_id({"34": "Deutschland (34)"}, 34),
            "34",
        )
        self.assertEqual(
            self.mapping.default_weather_country_id({"143": "USA (143)"}, 34),
            "143",
        )

    def test_weather_result_options_limit_and_label_results(self) -> None:
        self.assertEqual(
            self.mapping.weather_result_options(
                [
                    {"Name": "Essen", "Country": "Deutschland"},
                    {"LocationId": "ID=19"},
                ],
                max_options=1,
            ),
            {"0": "Essen, Deutschland"},
        )


class TestConfigFlowRadioMapping(unittest.TestCase):
    """Validate radio options mapping for flows."""

    def setUp(self) -> None:
        self.mapping = _load_config_flow_mapping()

    def test_radio_catalog_options_trim_and_drop_empty_values(self) -> None:
        self.assertEqual(
            self.mapping.radio_catalog_options(["  Deutschland ", "", "USA"]),
            {"Deutschland": "Deutschland", "USA": "USA"},
        )

    def test_default_radio_catalog_value_prefers_known_default(self) -> None:
        self.assertEqual(
            self.mapping.default_radio_catalog_value(
                "city",
                {"Düsseldorf/Nordrhein-Westfalen": "Düsseldorf/Nordrhein-Westfalen"},
                {"city": "Düsseldorf/Nordrhein-Westfalen"},
            ),
            "Düsseldorf/Nordrhein-Westfalen",
        )
        self.assertEqual(
            self.mapping.default_radio_catalog_value(
                "city",
                {"Essen/Nordrhein-Westfalen": "Essen/Nordrhein-Westfalen"},
                {"city": "Düsseldorf/Nordrhein-Westfalen"},
            ),
            "Essen/Nordrhein-Westfalen",
        )

    def test_radio_station_label_uses_name_location_description_and_id(self) -> None:
        self.assertEqual(
            self.mapping.radio_station_label(
                {
                    "Name": "WDR 2 Ruhrgebiet",
                    "City": "Essen",
                    "Country": "Deutschland",
                    "Id": 3,
                }
            ),
            "WDR 2 Ruhrgebiet - Essen, Deutschland (3)",
        )

    def test_filter_radio_results_by_text_searches_names_locations_and_genres(self) -> None:
        results = [
            {"Name": "WDR 2 Ruhrgebiet", "City": "Essen", "Genres": ["Pop"]},
            {"Name": "1Live", "City": "Köln", "Genres": ["Rock"]},
        ]

        self.assertEqual(
            self.mapping.filter_radio_results_by_text(results, "rock"),
            [{"Name": "1Live", "City": "Köln", "Genres": ["Rock"]}],
        )
        self.assertIs(self.mapping.filter_radio_results_by_text(results, "*"), results)


if __name__ == "__main__":
    unittest.main()
