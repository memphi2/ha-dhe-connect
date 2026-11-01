"""Tests for weather display mapping helpers."""

from __future__ import annotations

import math
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from tests.client_test_support import _load_component_module


def _load_weather_mapping():
    _load_component_module("entity_state_helpers")
    return _load_component_module("weather_mapping")


class TestWeatherForecastMapping(unittest.TestCase):
    """Validate forecast mapping behavior."""

    def setUp(self) -> None:
        self.weather = _load_weather_mapping()

    def test_invalid_numeric_fields_leave_valid_forecast_fields_intact(self) -> None:
        for value in ("NaN", "inf", "-inf", "1e309", float("nan"), True, 10**400):
            with self.subTest(value=value):
                day = {"date": "2026-11-01", "icon_id_day": value,
                       "preci_morning": value, "tmax": value, "tmin": 12}
                self.assertIsNone(self.weather.number(value))
                self.assertIsNone(self.weather.int_value(value))
                self.assertEqual(self.weather.current_temperature(day), 12)
                self.assertEqual(self.weather.forecast_from_day(day), {
                    "datetime": "2026-11-01T00:00:00+00:00", "native_templow": 12.0,
                })
                self.assertNotIn("icon_id_day", self.weather.weather_attributes({}, day, []))

    def test_finite_temperature_average_does_not_overflow(self) -> None:
        value = self.weather.current_temperature({"tmax": 1e308, "tmin": 1e308})
        self.assertTrue(math.isfinite(value))


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

    def test_forecast_from_day_keeps_device_calendar_date_at_utc_midnight(self) -> None:
        forecast = self.weather.forecast_from_day({"date": "2026-12-31"})

        self.assertEqual(forecast, {"datetime": "2026-12-31T00:00:00+00:00"})

    def test_forecast_from_day_converts_local_midnight_to_utc(self) -> None:
        forecast = self.weather.forecast_from_day(
            {"date": "2026-05-10"},
            time_zone=ZoneInfo("America/New_York"),
        )

        self.assertEqual(forecast, {"datetime": "2026-05-10T04:00:00+00:00"})

    def test_forecast_datetime_keeps_local_calendar_date_when_rendered(self) -> None:
        forecast_time = self.weather.forecast_datetime_from_date(
            "2026-05-10",
            time_zone=ZoneInfo("America/Los_Angeles"),
        )

        local_time = datetime.fromisoformat(forecast_time).astimezone(
            ZoneInfo("America/Los_Angeles")
        )
        self.assertEqual(local_time.date().isoformat(), "2026-05-10")
        self.assertEqual(local_time.hour, 0)

    def test_forecast_from_day_requires_date(self) -> None:
        self.assertIsNone(self.weather.forecast_from_day({"tmax": 19}))

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
