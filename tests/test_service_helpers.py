"""Tests for shared service helper behavior."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import unittest

from homeassistant.exceptions import HomeAssistantError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from custom_components.stiebel_dhe_connect import service_helpers  # noqa: E402


class _WeatherClient:
    last_weather_state = {"forecast_results": []}


class TestServiceHelpers(unittest.TestCase):
    """Validate pure weather service selection and error mapping."""

    def test_weather_locations_keeps_only_dict_items(self) -> None:
        self.assertEqual(
            service_helpers.weather_locations([{"LocationId": "one"}, "bad", None]),
            [{"LocationId": "one"}],
        )

    def test_select_weather_location_accepts_cached_favorite(self) -> None:
        location = service_helpers.select_weather_location(
            {"favorites": [{"LocationId": "favorite", "Name": "Favorite"}]},
            [],
            "favorite",
            1,
        )

        self.assertEqual(location, {"LocationId": "favorite", "Name": "Favorite"})

    def test_weather_location_payload_rejects_empty_raw_id(self) -> None:
        with self.assertRaises(HomeAssistantError) as ctx:
            service_helpers.weather_location_payload("")

        self.assertEqual(
            getattr(ctx.exception, "translation_key", None),
            "dhe_weather_location_id_empty",
        )

    def test_select_weather_location_rejects_zero_result_number(self) -> None:
        with self.assertRaises(HomeAssistantError) as ctx:
            service_helpers.select_weather_location(
                {},
                [{"LocationId": "one"}],
                None,
                0,
            )

        self.assertEqual(
            getattr(ctx.exception, "translation_key", None),
            "dhe_weather_result_unavailable",
        )

    def test_weather_result_lookup_requires_country_for_search_name(self) -> None:
        with self.assertRaises(HomeAssistantError) as ctx:
            asyncio.run(
                service_helpers.weather_results_from_service_input(
                    _WeatherClient(),
                    {service_helpers.ATTR_NAME: "Berlin"},
                    missing_country_error="country_id is required",
                )
            )

        self.assertEqual(
            getattr(ctx.exception, "translation_key", None),
            "dhe_weather_country_required",
        )


if __name__ == "__main__":
    unittest.main()
