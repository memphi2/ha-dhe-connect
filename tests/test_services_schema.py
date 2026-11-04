"""Numeric service inputs must match the advertised selector contracts."""

import probatio as vol
import pytest

from custom_components.stiebel_dhe_connect import services


@pytest.mark.parametrize("value", [-1, 0, 10000, 1.9, True, False, float("nan"), float("inf"), None, [], "1.9"])
@pytest.mark.parametrize("schema", [services.WEATHER_SEARCH_SCHEMA, services.WEATHER_LOCATION_ACTION_SCHEMA])
def test_country_rejects_invalid_values(value, schema):
    with pytest.raises(vol.Invalid):
        schema({"name": "Test", "country_id": value})


@pytest.mark.parametrize("value,expected", [(1, 1), (9999, 9999), (34.0, 34), ("34", 34)])
def test_country_accepts_bounded_integers(value, expected):
    assert services.WEATHER_SEARCH_SCHEMA({"name": "Test", "country_id": value})["country_id"] == expected


@pytest.mark.parametrize("value", [1.9, True, False, float("nan"), float("inf"), 0, -1, 999, "1.9", None, []])
def test_result_number_rejects_fractional_or_invalid_values(value):
    with pytest.raises(vol.Invalid):
        services.WEATHER_LOCATION_ACTION_SCHEMA({"result_number": value})


@pytest.mark.parametrize("value", [1, 1.0, "1", services.WEATHER_RESULT_NUMBER_MAX])
def test_result_number_accepts_whole_numbers(value):
    assert services.WEATHER_LOCATION_ACTION_SCHEMA({"result_number": value})["result_number"] == int(value)
