"""Tests for radio display mapping helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RADIO_MAPPING = (
    ROOT / "custom_components" / "stiebel_dhe_connect" / "radio_mapping.py"
)


def _load_radio_mapping():
    spec = importlib.util.spec_from_file_location("radio_mapping", RADIO_MAPPING)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestRadioDisplayMapping(unittest.TestCase):
    """Validate media-player radio mapping behavior."""

    def setUp(self) -> None:
        self.radio = _load_radio_mapping()

    def test_station_name_falls_back_to_id(self) -> None:
        self.assertEqual(self.radio.station_name({"Name": "WDR 2"}), "WDR 2")
        self.assertEqual(self.radio.station_name({"Id": 3}), "3")
        self.assertIsNone(self.radio.station_name({}))

    def test_station_logo_url_prefers_larger_images_and_fixes_scheme_relative_url(self) -> None:
        self.assertEqual(
            self.radio.station_logo_url(
                {
                    "Logo44Url": "https://small.example/logo.png",
                    "Logo175Url": "//large.example/logo.png",
                }
            ),
            "https://large.example/logo.png",
        )

    def test_source_option_map_disambiguates_duplicate_labels(self) -> None:
        options = self.radio.source_option_map(
            [
                {"Id": 1, "Name": "WDR 2"},
                {"Id": 2, "Name": "WDR 2"},
                {"Id": 3, "Name": "1Live"},
            ]
        )

        self.assertEqual(list(options), ["WDR 2 (1)", "WDR 2 (2)", "1Live"])

    def test_source_option_map_disambiguates_duplicate_labels_without_ids(self) -> None:
        options = self.radio.source_option_map(
            [
                {"Name": "WDR 2"},
                {"Name": "WDR 2"},
                {"Name": "WDR 2"},
            ]
        )

        self.assertEqual(list(options), ["WDR 2", "WDR 2 #2", "WDR 2 #3"])

    def test_source_for_station_matches_by_id(self) -> None:
        sources = {
            "WDR 2 (1)": {"Id": 1, "Name": "WDR 2"},
            "WDR 2 (2)": {"Id": 2, "Name": "WDR 2"},
        }

        self.assertEqual(self.radio.source_for_station({"Id": "2"}, sources), "WDR 2 (2)")

    def test_source_for_state_uses_first_source_when_station_is_unknown(self) -> None:
        sources = {
            "Radio Essen": {"Id": 971, "Name": "Radio Essen"},
            "WDR 2": {"Id": 3, "Name": "WDR 2"},
        }

        self.assertEqual(self.radio.source_for_state(None, sources), "Radio Essen")

    def test_source_for_state_preserves_current_source_without_station(self) -> None:
        sources = {
            "Radio Essen": {"Id": 971, "Name": "Radio Essen"},
            "WDR 2": {"Id": 3, "Name": "WDR 2"},
        }

        self.assertEqual(
            self.radio.source_for_state(None, sources, "WDR 2"),
            "WDR 2",
        )

    def test_source_option_map_for_state_preserves_sources_without_favorites(self) -> None:
        sources = {"WDR 2": {"Id": 3, "Name": "WDR 2"}}

        options = self.radio.source_option_map_for_state(
            {"play": True},
            sources,
        )

        self.assertEqual(options, sources)
        self.assertIsNot(options["WDR 2"], sources["WDR 2"])

    def test_source_option_map_for_state_uses_current_station_before_favorites(self) -> None:
        options = self.radio.source_option_map_for_state(
            {"station": {"Id": 3, "Name": "WDR 2 Ruhrgebiet"}}
        )

        self.assertEqual(list(options), ["WDR 2 Ruhrgebiet"])

    def test_source_option_map_for_state_adds_station_to_existing_sources(self) -> None:
        options = self.radio.source_option_map_for_state(
            {"station": {"Id": 971, "Name": "Radio Essen"}},
            {"WDR 2": {"Id": 3, "Name": "WDR 2"}},
        )

        self.assertEqual(list(options), ["WDR 2", "Radio Essen"])

    def test_source_option_map_for_state_refreshes_matching_station(self) -> None:
        options = self.radio.source_option_map_for_state(
            {"station": {"Id": 3, "Name": "WDR 2 Ruhrgebiet"}},
            {"WDR 2": {"Id": 3, "Name": "WDR 2"}},
        )

        self.assertEqual(
            options,
            {"WDR 2 Ruhrgebiet": {"Id": 3, "Name": "WDR 2 Ruhrgebiet"}},
        )

    def test_source_option_map_for_state_replaces_sources_from_favorites(self) -> None:
        options = self.radio.source_option_map_for_state(
            {
                "station": {"Id": 3, "Name": "WDR 2 Ruhrgebiet"},
                "favorites": [
                    {"Id": 971, "Name": "Radio Essen"},
                    {"Id": 3, "Name": "WDR 2 Ruhrgebiet"},
                ],
            },
            {"Old": {"Id": 1, "Name": "Old"}},
        )

        self.assertEqual(list(options), ["Radio Essen", "WDR 2 Ruhrgebiet"])

    def test_media_title_prefers_current_radio_title(self) -> None:
        title = self.radio.media_title(
            {"title": "Vitamin Z - Dont Stop And Listen to His Music - 1985"},
            {
                "Name": "Radio Essen",
                "ShortDescription": "100% von hier. Der beste Mix.",
            },
        )

        self.assertEqual(title, "Vitamin Z - Dont Stop And Listen to His Music - 1985")

    def test_media_title_falls_back_to_short_description(self) -> None:
        title = self.radio.media_title(
            {},
            {
                "Name": "Radio Essen",
                "ShortDescription": "100% von hier. Der beste Mix.",
            },
        )

        self.assertEqual(title, "100% von hier. Der beste Mix.")

    def test_media_title_falls_back_to_station_name(self) -> None:
        self.assertEqual(
            self.radio.media_title({}, {"Name": "Radio Essen"}),
            "Radio Essen",
        )

    def test_radio_attributes_summarize_station_and_favorites(self) -> None:
        attributes = self.radio.radio_attributes(
            {
                "station": {
                    "Id": 3,
                    "Name": "WDR 2 Ruhrgebiet",
                    "City": "Essen",
                    "Genres": ["Pop", 80],
                },
                "favorites": [{"Id": 3, "Name": "WDR 2 Ruhrgebiet"}],
                "title": "Queen - A Kind Of Magic",
                "paired": False,
            }
        )

        self.assertEqual(attributes["station_id"], 3)
        self.assertEqual(attributes["station_name"], "WDR 2 Ruhrgebiet")
        self.assertEqual(attributes["station_city"], "Essen")
        self.assertEqual(attributes["station_genres"], ["Pop", "80"])
        self.assertEqual(attributes["favorite_count"], 1)
        self.assertEqual(attributes["title"], "Queen - A Kind Of Magic")
        self.assertFalse(attributes["bluetooth_paired"])


if __name__ == "__main__":
    unittest.main()
