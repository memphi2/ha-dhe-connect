"""Tests for weather display mapping helpers."""

from __future__ import annotations

from datetime import datetime
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WEATHER_MAPPING = (
    ROOT / "custom_components" / "stiebel_dhe_connect" / "weather_mapping.py"
)


def _load_weather_mapping():
    spec = importlib.util.spec_from_file_location("weather_mapping", WEATHER_MAPPING)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestWeatherForecastMapping(unittest.TestCase):
    """Validate forecast mapping behavior."""

    def setUp(self) -> None:
        self.weather = _load_weather_mapping()

    def test_forecast_source_days_prefers_complete_days_and_deduplicates(self) -> None:
        days = self.weather.forecast_source_days(
            {
                "complete_days": [
                    {"date": "2026-05-10", "tmax": 19},
                    {"date": "2026-05-10", "tmax": 20},
                    {"date": "2026-05-11", "tmax": 11},
                ],
                "simple_days": [{"date": "ignored"}],
            }
        )

        self.assertEqual(
            days,
            [
                {"date": "2026-05-10", "tmax": 19},
                {"date": "2026-05-11", "tmax": 11},
            ],
        )

    def test_forecast_from_day_maps_condition_temperature_and_precipitation(self) -> None:
        forecast = self.weather.forecast_from_day(
            {
                "date": "2026-05-10",
                "icon_id_day": 7,
                "preci_morning": 80,
                "tmax": 19,
                "tmin": 10,
            }
        )

        self.assertEqual(
            forecast,
            {
                "datetime": "2026-05-10T00:00:00+00:00",
                "condition": "pouring",
                "native_temperature": 19.0,
                "native_templow": 10.0,
                "precipitation_probability": 80,
            },
        )

    def test_current_weather_period_boundaries(self) -> None:
        self.assertEqual(
            self.weather.current_weather_period(datetime(2026, 5, 10, 11, 59)),
            "morning",
        )
        self.assertEqual(
            self.weather.current_weather_period(datetime(2026, 5, 10, 12, 0)),
            "midday",
        )
        self.assertEqual(
            self.weather.current_weather_period(datetime(2026, 5, 10, 18, 0)),
            "evening",
        )

    def test_current_temperature_uses_supplied_weather_period(self) -> None:
        day = {
            "temp_morning": 8,
            "temp_midday": 14,
            "temp_evening": 10,
        }

        self.assertEqual(
            self.weather.current_temperature(day, now=datetime(2026, 5, 10, 19, 0)),
            10.0,
        )

    def test_weather_attributes_use_supplied_weather_period(self) -> None:
        attributes = self.weather.weather_attributes(
            {},
            {},
            [],
            now=datetime(2026, 5, 10, 19, 0),
        )

        self.assertEqual(attributes["current_period"], "evening")


class TestWeatherLocationMapping(unittest.TestCase):
    """Validate weather location labels and attributes."""

    def setUp(self) -> None:
        self.weather = _load_weather_mapping()

    def test_weather_location_name_prefers_int_names(self) -> None:
        self.assertEqual(
            self.weather.weather_location_name(
                {
                    "Name": "Fallback",
                    "IntNames": [{"Name": "New York", "SearchType": 3}],
                }
            ),
            "New York",
        )

    def test_weather_location_attributes_include_search_type_from_int_names(self) -> None:
        attributes = self.weather.weather_location_attributes(
            {
                "Country": "USA",
                "CountryId": 143,
                "LocationId": "ID=19@COUNTRY_ID=143",
                "IntNames": [{"Name": "New York", "SearchType": "3"}],
            }
        )

        self.assertEqual(attributes["country"], "USA")
        self.assertEqual(attributes["country_id"], 143)
        self.assertEqual(attributes["location_id"], "ID=19@COUNTRY_ID=143")
        self.assertEqual(attributes["search_type"], 3)
        self.assertEqual(attributes["int_names"], [{"Name": "New York", "SearchType": "3"}])

    def test_weather_entity_name_uses_city_and_country(self) -> None:
        self.assertEqual(
            self.weather.weather_entity_name(
                {"location": {"Name": "San Francisco", "Country": "USA"}}
            ),
            "San Francisco, USA",
        )

    def test_weather_attributes_summarize_location_favorites_and_icons(self) -> None:
        location = {
            "Name": "Essen",
            "Country": "Deutschland",
            "CountryId": 34,
            "LocationId": "ID=320",
        }

        attributes = self.weather.weather_attributes(
            {
                "location": location,
                "favorites": [location],
                "forecast_results": [{"Name": "New York", "Country": "USA"}],
                "country_id": "34",
            },
            {"icon_id_day": 4, "preci_morning": 20, "preci_midday": 20},
            [{"datetime": "2026-05-10T00:00:00+00:00"}],
        )

        self.assertEqual(attributes["location"], "Essen, Deutschland")
        self.assertEqual(attributes["favorite_count"], 1)
        self.assertTrue(attributes["is_favorite"])
        self.assertEqual(attributes["icon_day"], "partly_cloudy")
        self.assertEqual(attributes["condition_day"], "partlycloudy")
        self.assertEqual(attributes["selected_country_id"], 34)


if __name__ == "__main__":
    unittest.main()
