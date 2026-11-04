"""Verify catalog requests, favorite safety and explicit command readbacks."""

import json
import sys
from unittest.mock import AsyncMock

import pytest

from tests.client_behavior_support import make_client
from tests.client_test_support import PACKAGE_NAME


@pytest.fixture
async def device(monkeypatch):
    return make_client(monkeypatch)


def posted_payload(client):
    packet = client._post_packet.call_args.args[1]
    return json.loads(packet[packet.index("[") :])[1]


@pytest.mark.parametrize(
    "method,value,field,expected",
    [
        ("set_radio_play", True, "play", True),
        ("set_radio_volume", 0.426, "volume", 43),
        ("set_radio_volume", 2, "volume", 100),
        ("set_radio_volume", -1, "volume", 0),
    ],
)
async def test_radio_controls_confirm_local_state(
    device, method, value, field, expected
):
    client, _ = device
    result = await getattr(client, method)(value)
    client._send_ste_command.assert_awaited_once_with(
        client._ctx, f"assign:ste.app.radio:{field}", expected
    )
    assert result == (expected / 100 if field == "volume" else expected)
    assert client.last_radio_state[field] == expected


async def test_radio_pairing_disconnect_and_unsupported_assignment(device):
    client, module = device
    assert await client.disconnect_radio_pairing()
    assert client.last_radio_state["paired"] is False
    with pytest.raises(module.DHEError, match="Unsupported"):
        await client._assign_radio_value("unsupported", True)
    assert client._send_ste_command.await_count == 1


@pytest.mark.parametrize("catalog", ["genre", "country", "city"])
async def test_radio_catalog_requests_and_generation(device, catalog):
    client, _ = device
    client._radio_catalog_generations[catalog] = 3
    client._wait_for_radio_catalog = AsyncMock(return_value=["Example"])
    result = await (
        client.list_radio_genres()
        if catalog == "genre"
        else client.list_radio_catalog(catalog.upper())
    )
    assert result == ["Example"]
    client._request_app_value.assert_awaited_once_with(
        client._ctx, f"get:ste.app.radio:{catalog}"
    )
    client._wait_for_radio_catalog.assert_awaited_once_with(catalog, 3)


@pytest.mark.parametrize(
    "attribute,value,text",
    [("genre", "Rock", None), ("country", "Example", "FM"), ("text", "Example", None)],
)
async def test_radio_search_serializes_normalized_input(device, attribute, value, text):
    client, _ = device
    client._wait_for_radio_stations = AsyncMock(return_value=[{"Id": 9}])
    result = await (
        client.search_radio_stations_by_genre(value)
        if attribute == "genre"
        else client.search_radio_stations(
            f" {attribute.upper()} ", f" {value} ", search_text=text
        )
    )
    assert result == [{"Id": 9}]
    expected = {"attribute": attribute, "value": value}
    if text:
        expected["text"] = text
    assert posted_payload(client)["value"] == expected
    client._wait_for_radio_stations.assert_awaited_once_with(0)


@pytest.mark.parametrize(
    "method,args,kwargs",
    [
        ("list_radio_catalog", ["invalid"], {}),
        ("search_radio_stations", ["invalid", "name"], {}),
        ("search_radio_stations", ["text", " "], {}),
        ("search_radio_stations", ["text", "name"], {"search_text": " "}),
        ("select_radio_station", [{}], {}),
        ("search_weather_locations", [" ", 34], {}),
        ("toggle_weather_favorite", [{}], {}),
        ("add_weather_favorite", [{}], {}),
        ("remove_weather_favorite", [{}], {}),
        ("select_weather_location", [{}], {}),
    ],
)
async def test_invalid_catalog_commands_never_contact_transport(
    device, method, args, kwargs
):
    client, module = device
    with pytest.raises(module.DHEError):
        await getattr(client, method)(*args, **kwargs)
    client._post_packet.assert_not_awaited()
    client._send_ste_command.assert_not_awaited()


async def test_weather_search_and_country_catalog(device):
    client, _ = device
    client._wait_for_weather_search_results = AsyncMock(
        return_value=[{"LocationId": "fixture"}]
    )
    client._wait_for_weather_countries = AsyncMock(return_value=[{"CountryId": 34}])
    assert await client.search_weather_locations(" Example ", "34") == [
        {"LocationId": "fixture"}
    ]
    assert posted_payload(client)["value"] == {"name": "Example", "countryId": 34}
    assert await client.list_weather_countries() == [{"CountryId": 34}]
    client._wait_for_weather_countries.assert_awaited_once_with(0)


@pytest.mark.parametrize(
    "kind,item", [("radio", {"Id": 9}), ("weather", {"LocationId": "fixture"})]
)
async def test_favorite_lists_and_refresh_after_missing_confirmation(
    device, kind, item
):
    client, module = device
    waiter = AsyncMock(return_value=[item])
    setattr(client, f"_wait_for_{kind}_favorites", waiter)
    assert await getattr(client, f"list_{kind}_favorites")() == [item]
    waiter.side_effect = [module.DHEError("no update"), [item]]
    result = await getattr(client, f"_assign_{kind}_favorite_and_wait")(
        client._ctx, item["Id"] if kind == "radio" else item
    )
    assert result == [item]
    assert client._request_app_value.await_count == 2


@pytest.mark.parametrize(
    "kind,item", [("radio", {"Id": 9}), ("weather", {"LocationId": "fixture"})]
)
@pytest.mark.parametrize("present", [False, True])
async def test_removal_checks_fresh_list_and_confirmation(device, kind, item, present):
    client, _ = device
    request = AsyncMock(return_value=[item] if present else [])
    assign = AsyncMock(return_value=[])
    setattr(client, f"_request_{kind}_favorites", request)
    setattr(client, f"_assign_{kind}_favorite_and_wait", assign)
    assert await getattr(client, f"remove_{kind}_favorite")(item)
    assert assign.await_count == int(present)
    request.assert_awaited_once_with(client._ctx)


@pytest.mark.parametrize(
    "kind,item", [("radio", {"Id": 9}), ("weather", {"LocationId": "fixture"})]
)
async def test_removal_rejects_unchanged_readback(device, kind, item):
    client, module = device
    setattr(client, f"_request_{kind}_favorites", AsyncMock(return_value=[item]))
    setattr(client, f"_assign_{kind}_favorite_and_wait", AsyncMock(return_value=[item]))
    with pytest.raises(module.DHEError, match="did not change"):
        await getattr(client, f"remove_{kind}_favorite")(item)


async def test_radio_selection_tolerates_lost_station_ack(device):
    client, module = device
    client._wait_for_radio_station = AsyncMock(
        side_effect=module.DHEError("no acknowledgement")
    )
    assert await client.select_radio_station(9)
    client._send_ste_command.assert_awaited_once_with(
        client._ctx, "assign:ste.app.radio:station", 9
    )


async def test_weather_toggle_is_not_retried_and_selection_is_confirmed(device):
    client, module = device
    location = {"LocationId": "fixture", "Name": "Example"}
    client._assign_weather_favorite_and_wait = AsyncMock(return_value=[location])
    assert await client.toggle_weather_favorite(location)
    sent = client._assign_weather_favorite_and_wait.call_args.args[1]
    assert sent == location and sent is not location
    client._assign_weather_favorite_and_wait.side_effect = module.DHEError(
        "lost acknowledgement"
    )
    with pytest.raises(module.DHEError):
        await client.toggle_weather_favorite(location)
    assert client._assign_weather_favorite_and_wait.await_count == 2
    client._force_reconnect.assert_not_awaited()
    client._wait_for_weather_location = AsyncMock()
    assert await client.select_weather_location(location)
    client._wait_for_weather_location.assert_awaited_once_with("fixture")


async def test_wellness_start_and_stop_publish_consistent_state(device):
    client, _ = device
    protocol = sys.modules[f"{PACKAGE_NAME}.protocol"]
    client.write_odb_value = AsyncMock()
    assert await client.set_wellness_shower_program(2)
    assert client.write_odb_value.await_args_list[0].args == (
        protocol.ID_WELLNESS_SHOWER_PROGRAM,
        2,
    )
    assert await client.stop_wellness_shower_program() is False
    assert client.last_measurements[protocol.ID_WELLNESS_ACTIVE] is False
    assert client.last_measurements[protocol.ID_WELLNESS_SHOWER_PROGRAM] == 0


async def test_app_write_timeout_clears_confirmation_future(device):
    client, module = device
    client._wait_for_app_write_confirmation = AsyncMock(side_effect=TimeoutError)
    with pytest.raises(module.DHEError, match="No DHE app confirmation"):
        await client.set_brush_timer_activation(True)
    assert client._pending_write_future is None
