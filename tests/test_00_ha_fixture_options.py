"""Exercise options forms, validation and device failures with real HA flows."""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.ha_test_support import (
    DOMAIN,
    _async_test_home_assistant,
    _build_mock_entry,
    _clear_loaded_integration_modules,
)

LOCATION = {
    "LocationId": "fixture-location",
    "Name": "Example City",
    "Country": "Example",
}
STATION = {"Id": 12, "Name": "Example FM", "Country": "Example"}


@pytest.fixture
async def options_flow(tmp_path):
    _clear_loaded_integration_modules()
    module = importlib.import_module(f"custom_components.{DOMAIN}.config_flow_options")
    async with _async_test_home_assistant(config_dir=str(tmp_path)) as hass:
        entry = _build_mock_entry(
            host="device.invalid", port=8443, name="Test", unique_id="fixture"
        )
        entry.add_to_hass(hass)
        client = SimpleNamespace(last_measurements={})
        for method, result in {
            "list_weather_countries": [{"CountryId": 34, "Country": "Example"}],
            "search_weather_locations": [LOCATION],
            "list_weather_favorites": [LOCATION],
            "add_weather_favorite": True,
            "remove_weather_favorite": True,
            "list_radio_catalog": ["Example"],
            "search_radio_stations": [STATION],
            "list_radio_favorites": [STATION],
            "add_radio_favorite": True,
            "remove_radio_favorite": True,
            "set_electricity_price": 0.25,
            "set_water_price": 3.0,
            "set_co2_emission": 0.2,
        }.items():
            setattr(client, method, AsyncMock(return_value=result))
        entry.runtime_data = SimpleNamespace(client=client)
        flow = module.StiebelDHEConnectOptionsFlow()
        flow.hass, flow.handler, flow.flow_id = hass, entry.entry_id, "fixture-options"
        yield flow, client, module


async def test_options_menu_and_device_settings_preserve_options(options_flow):
    flow, client, _ = options_flow
    menu = await flow.async_step_init()
    assert len(menu["menu_options"]) == 6
    form = await flow.async_step_device_settings()
    assert form["errors"] == {}
    result = await flow.async_step_device_settings(
        {"electricity_price": "0,25", "water_price": "3", "co2_emission": "0.2"}
    )
    assert result["type"] == "create_entry"
    assert result["data"] == dict(flow.config_entry.options)
    client.set_electricity_price.assert_awaited_once_with(0.25)
    client.set_water_price.assert_awaited_once_with(3.0)
    client.set_co2_emission.assert_awaited_once_with(0.2)


@pytest.mark.parametrize(
    "step",
    [
        "device_settings",
        "weather_favorite",
        "weather_favorite_result",
        "remove_weather_favorite",
        "radio_favorite_catalog",
        "radio_favorite_result",
        "remove_radio_favorite",
    ],
)
async def test_unloaded_options_report_not_loaded(options_flow, step):
    flow, _, _ = options_flow
    flow.config_entry.runtime_data = None
    result = await getattr(flow, f"async_step_{step}")()
    assert result["errors"]["base"] == "not_loaded"


@pytest.mark.parametrize(
    "scenario,expected",
    [
        ("country_failure", "cannot_connect"),
        ("no_countries", "no_countries"),
        ("search_failure", "search_failed"),
        ("empty", "no_results"),
        ("name", "required"),
        ("country", "invalid_country"),
    ],
)
async def test_weather_search_failures(options_flow, scenario, expected):
    flow, client, module = options_flow
    data = {"name": "Example", "country_id": "34"}
    if scenario == "country_failure":
        client.list_weather_countries.side_effect = module.DHEError("offline")
    elif scenario == "no_countries":
        client.list_weather_countries.return_value = []
        data = None
    elif scenario == "search_failure":
        client.search_weather_locations.side_effect = module.DHEError("offline")
    elif scenario == "empty":
        client.search_weather_locations.return_value = []
    elif scenario == "name":
        data["name"] = " "
    else:
        data["country_id"] = "invalid"
    result = await flow.async_step_weather_favorite(data)
    assert expected in result["errors"].values()
    client.add_weather_favorite.assert_not_awaited()


async def test_weather_search_and_selection(options_flow):
    flow, client, _ = options_flow
    form = await flow.async_step_weather_favorite(
        {"name": " Example ", "country_id": "34"}
    )
    assert form["step_id"] == "weather_favorite_result"
    assert form["data_schema"]({"result": "0"}) == {"result": "0"}
    client.search_weather_locations.assert_awaited_once_with("Example", 34)
    result = await flow.async_step_weather_favorite_result({"result": "0"})
    assert result["type"] == "create_entry"
    client.add_weather_favorite.assert_awaited_once_with(LOCATION)


@pytest.mark.parametrize("kind", ["weather", "radio"])
@pytest.mark.parametrize("remove", [False, True])
@pytest.mark.parametrize("scenario", ["success", "empty", "invalid", "device_failure"])
async def test_favorite_forms(options_flow, kind, remove, scenario):
    flow, client, module = options_flow
    items = [LOCATION if kind == "weather" else STATION]
    step = f"remove_{kind}_favorite" if remove else f"{kind}_favorite_result"
    if remove:
        getattr(client, f"list_{kind}_favorites").return_value = (
            [] if scenario == "empty" else items
        )
        form = await getattr(flow, f"async_step_{step}")()
    else:
        setattr(flow, f"_{kind}_results", [] if scenario == "empty" else items)
        form = await getattr(flow, f"async_step_{step}")()
    method = getattr(client, f"{'remove' if remove else 'add'}_{kind}_favorite")
    if scenario == "empty":
        assert form["errors"]
        method.assert_not_awaited()
        return
    assert form["errors"] == {}
    if scenario == "device_failure":
        method.side_effect = module.DHEError("device rejected")
    result = await getattr(flow, f"async_step_{step}")(
        {"result": "999" if scenario == "invalid" else "0"}
    )
    if scenario == "success":
        assert result["type"] == "create_entry"
        method.assert_awaited_once_with(
            items[0], **({"select": True} if kind == "radio" and not remove else {})
        )
    else:
        assert result["type"] == "form"
        assert result["errors"]
        if scenario == "invalid":
            method.assert_not_awaited()


@pytest.mark.parametrize("kind", ["weather", "radio"])
async def test_remove_favorite_list_failure(options_flow, kind):
    flow, client, module = options_flow
    getattr(client, f"list_{kind}_favorites").side_effect = module.DHEError("offline")
    result = await getattr(flow, f"async_step_remove_{kind}_favorite")()
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.parametrize("search_type", ["text", "genre", "country", "city"])
async def test_radio_search_routes_and_filters(options_flow, search_type):
    flow, client, _ = options_flow
    form = await flow.async_step_radio_favorite({"search_type": search_type})
    assert form["step_id"] == "radio_favorite_catalog"
    data = {"selection": "Example", "filter_text": "Example"}
    result = await flow.async_step_radio_favorite_catalog(data)
    assert result["step_id"] == "radio_favorite_result"
    assert flow._radio_results == [STATION]
    client.search_radio_stations.assert_awaited_once_with(
        search_type,
        "Example",
        search_text="Example" if search_type in {"country", "city"} else None,
    )
    assert client.list_radio_catalog.await_count == (0 if search_type == "text" else 1)


@pytest.mark.parametrize(
    "scenario,expected",
    [
        ("type", "invalid_radio_search_type"),
        ("catalog_failure", "radio_catalog_failed"),
        ("empty_catalog", "no_radio_catalog"),
        ("missing_selection", "required"),
        ("invalid_selection", "invalid_radio_catalog_value"),
        ("missing_filter", "required"),
        ("search_failure", "radio_search_failed"),
        ("empty_search", "no_results"),
    ],
)
async def test_radio_input_and_transport_errors(options_flow, scenario, expected):
    flow, client, module = options_flow
    flow._radio_search_type = "country"
    data = {"selection": "Example", "filter_text": "*"}
    if scenario == "type":
        result = await flow.async_step_radio_favorite({"search_type": "invalid"})
        assert expected in result["errors"].values()
        flow._radio_search_type = "invalid"
        assert flow._effective_radio_search_type() == "text"
        return
    if scenario == "catalog_failure":
        client.list_radio_catalog.side_effect = module.DHEError("offline")
    elif scenario == "empty_catalog":
        client.list_radio_catalog.return_value = []
    elif scenario == "missing_selection":
        data["selection"] = ""
    elif scenario == "invalid_selection":
        data["selection"] = "other"
    elif scenario == "missing_filter":
        data["filter_text"] = " "
    elif scenario == "search_failure":
        client.search_radio_stations.side_effect = module.DHEError("offline")
    else:
        client.search_radio_stations.return_value = []
    result = await flow.async_step_radio_favorite_catalog(data)
    assert expected in result["errors"].values()
    client.add_radio_favorite.assert_not_awaited()
