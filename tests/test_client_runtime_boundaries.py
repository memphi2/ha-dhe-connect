"""Runtime protocol boundaries, derived values and readback confirmation paths."""

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tests.client_behavior_support import make_client
from tests.client_test_support import PACKAGE_NAME


@pytest.fixture
async def device(monkeypatch):
    client, module = make_client(monkeypatch)
    return client, module, sys.modules[f"{PACKAGE_NAME}.protocol"]


@pytest.mark.parametrize(
    "name,data,category",
    [
        ("other", {}, "ignored_event"),
        ("message", [], "invalid_message_payload"),
        ("message", {"command": 12}, "invalid_command"),
        ("message", {"command": "set:ste.app.radio:unsupported"}, "radio_unhandled"),
        (
            "message",
            {"command": "set:ste.common.odb:value", "value": []},
            "invalid_odb_payload",
        ),
        (
            "message",
            {"command": "set:ste.common.odb:value", "value": {"id": "bad"}},
            "invalid_odb_id",
        ),
        ("message", {"command": "set:ste.unknown:value"}, "unhandled"),
    ],
)
async def test_malformed_or_unknown_events_are_classified_without_state(
    device, name, data, category
):
    client, _, _ = device
    event_type = sys.modules[f"{PACKAGE_NAME}.client_types"].DHEEvent
    await client._handle_runtime_event(event_type(name, data))
    assert client._runtime_parser_stats[category] == 1
    assert client.last_measurements == {}


@pytest.mark.parametrize("reason", [None, "", "fixture disconnect"])
async def test_session_close_records_reconnect_reason(device, reason):
    client, _, _ = device
    with pytest.raises(sys.modules[f"{PACKAGE_NAME}.client_types"].DHESessionClosed):
        await client._handle_runtime_event(
            sys.modules[f"{PACKAGE_NAME}.client_types"].DHEEvent("__closed", reason)
        )
    assert client.diagnostic_state["connection_state"] == "reconnecting"
    assert client._runtime_parser_stats["socket_closed"] == 1


async def test_derived_bath_fill_prices_power_and_emissions(device):
    client, _, p = device
    for measurement, value in [
        (p.ID_BATH_FILL_TARGET_VOLUME, 100),
        (p.ID_BATH_FILL_CURRENT_VOLUME, 30),
        (p.ID_POWER_PERCENT, 50),
        (p.ID_NOMINAL_POWER, 2400),
        (p.ID_CO2_EMISSION_RAW, 321),
    ]:
        client._handle_odb_value(measurement, value)
    assert client.last_measurements[p.ID_BATH_FILL_REMAINING_VOLUME] == 70
    assert client.last_measurements[p.ID_NOMINAL_POWER] == 24
    assert client.last_measurements[p.ID_POWER_PERCENT] == 12
    assert client.last_measurements[p.ID_CO2_EMISSION] == 0.321
    for measurement, euros, cents in set(p.PRICE_COMPONENT_IDS.values()):
        client._handle_odb_value(euros, 2)
        client._handle_odb_value(cents, 35)
        assert client.last_measurements[measurement] == 2.35
    client._handle_odb_value(p.ID_BATH_FILL_CURRENT_VOLUME, 120)
    assert client.last_measurements[p.ID_BATH_FILL_REMAINING_VOLUME] == 0
    client._last_measurements[p.ID_BATH_FILL_CURRENT_VOLUME] = "invalid"
    client._refresh_bath_fill_remaining()
    assert client.last_measurements[p.ID_BATH_FILL_REMAINING_VOLUME] == 0


@pytest.mark.parametrize("raw,expected", [(24, 24), (240, 24), (2400, 24), (9999, 24)])
async def test_nominal_power_scaling_and_invalid_fallback(device, raw, expected):
    assert device[0]._raw_nominal_power_to_kw(raw) == expected


async def test_odb_conversion_classes_and_invalid_error_codes(device):
    client, _, p = device
    for measurement in p.ODB_NONNEGATIVE_VALUE_IDS:
        client._handle_odb_value(measurement, 12)
        assert client.last_measurements[measurement] == 12
    for measurement in p.ODB_DECILITER_VALUE_IDS:
        client._handle_odb_value(measurement, 123)
        assert client.last_measurements[measurement] == 12.3
    before = dict(client.last_measurements)
    for measurement in p.ODB_IGNORED_VALUE_IDS:
        client._handle_odb_value(measurement, 1)
    client._handle_odb_value(99999, 1)
    assert client.last_measurements == before
    assert client._convert_odb_value(p.ID_CHILD_SAFETY_TEMPERATURE_LIMIT, 420) == 42
    assert client._convert_odb_value(p.ID_CHILD_SAFETY_TEMPERATURE_LIMIT, 42) == 42
    assert client._convert_odb_value(p.ID_ECO_FLOW_LIMIT, 85) == 8.5
    assert client._convert_odb_value(p.ID_ECO_FLOW_LIMIT, 8.5) == 8.5
    runtime = sys.modules[f"{PACKAGE_NAME}.client_runtime"]
    assert runtime._extract_odb_error_code({"error": "invalid"}) is None
    assert runtime._extract_odb_error_code([]) is None
    assert client._odb_debug_name(None) == "unknown"


@pytest.mark.parametrize("kind", ["setpoint", "write"])
@pytest.mark.parametrize("scenario", ["already_done", "readback", "timeout"])
async def test_confirmation_waiters_only_accept_actual_readback(
    device, monkeypatch, kind, scenario
):
    client, module, p = device
    runtime = sys.modules[f"{PACKAGE_NAME}.client_runtime"]
    future = asyncio.get_running_loop().create_future()
    if scenario == "already_done":
        future.set_result(42.0)

    async def request(*_args):
        future.set_result(42.0)

    client._request_setpoint = AsyncMock(side_effect=request)
    client._request_odb_value = AsyncMock(side_effect=request)
    args = (
        (client._ctx, future)
        if kind == "setpoint"
        else (client._ctx, future, p.ID_SETPOINT)
    )
    waiter = getattr(client, f"_wait_for_{kind}_confirmation")
    if scenario == "timeout":
        monkeypatch.setattr(runtime, "COMMAND_CONFIRMATION_TIMEOUT", 0)
        with pytest.raises(module.DHEError, match="timed out"):
            await waiter(*args)
        assert not future.done()
        future.cancel()
    else:
        assert await waiter(*args) == 42.0
        assert (
            client._request_setpoint.await_count + client._request_odb_value.await_count
            == int(scenario == "readback")
        )


async def test_diagnostic_changes_and_expired_read_requests(device):
    client, _, _ = device
    callback = Mock()
    client._diagnostic_callbacks.add(callback)
    client._update_diagnostics(example="value")
    client._update_diagnostics(example="value")
    assert callback.call_count == 1
    client._update_diagnostics(example=None)
    assert "example" not in client.diagnostic_state
    client._pending_app_read_deadlines["set:example"] = -1
    assert not client._app_read_source("set:example")
    client._diagnostic_state = None
    client._update_diagnostics(example="ignored")
    assert client._copy_diagnostic_state() == {}


@pytest.mark.parametrize(
    "field,value", [("volume", "bad"), ("play", []), ("paired", {}), ("station", "bad")]
)
async def test_malformed_radio_updates_preserve_last_state(device, field, value):
    client, _, _ = device
    client._last_radio_state = {field: "previous"}
    client._handle_radio_value(f"set:ste.app.radio:{field}", value)
    assert client.last_radio_state == {field: "previous"}


async def test_radio_catalog_and_optional_text_are_independent_from_favorites(device):
    client, _, p = device
    client._handle_radio_value(p.RADIO_GENRE_SET_COMMAND, ["Rock", "Jazz"])
    assert client._last_radio_genres == ["Rock", "Jazz"]
    assert client._radio_genres_generation == 1
    client._handle_radio_catalog_value("set:ste.app.radio:unknown", [])
    client._handle_radio_catalog_value(p.RADIO_GENRE_SET_COMMAND, None)
    assert client._radio_genres_generation == 1
    client._handle_radio_value("set:ste.app.radio:title", None)
    assert client.last_radio_state["title"] == ""
    client._handle_radio_stations_value(None)
    client._handle_radio_favorites_value(None)
    assert client._radio_favorites_generation == client._radio_stations_generation == 0
    client._last_radio_favorites = [{"Id": 1}]
    client._radio_favorites_generation = 1
    assert client._copy_radio_state()["favorites"] == [{"Id": 1}]


@pytest.mark.parametrize(
    "kind",
    [
        "radio_stations",
        "radio_favorites",
        "weather_search_results",
        "weather_favorites",
        "weather_countries",
        "radio_catalog",
        "radio_station",
        "weather_location",
    ],
)
@pytest.mark.parametrize("success", [False, True])
async def test_media_waiters_success_or_bounded_timeout(
    device, monkeypatch, kind, success
):
    client, module, _ = device
    media = sys.modules[f"{PACKAGE_NAME}.client_runtime_media"]
    monkeypatch.setattr(media, "APP_COMMAND_CONFIRMATION_TIMEOUT", 1 if success else 0)
    monkeypatch.setattr(media, "WEATHER_CATALOG_TIMEOUT", 1 if success else 0)
    for attr in (
        "_radio_stations_generation",
        "_radio_favorites_generation",
        "_weather_search_generation",
        "_weather_favorites_generation",
        "_weather_countries_generation",
    ):
        setattr(client, attr, int(success))
    client._radio_catalog_generations["genre"] = int(success)
    if success:
        client._last_radio_stations = [{"Id": 1}]
        client._last_radio_favorites = [{"Id": 1}]
        client._last_radio_catalogs["genre"] = ["Rock"]
        client._last_radio_state["station"] = {"Id": 1}
        client._last_weather_countries = [{"CountryId": 34}]
        client._last_weather_state = {
            "location": {"LocationId": "fixture"},
            "forecast_results": [{"LocationId": "fixture"}],
            "favorites": [{"LocationId": "fixture"}],
        }
    args = (
        ("genre", 0)
        if kind == "radio_catalog"
        else (
            (1,)
            if kind == "radio_station"
            else (("fixture",) if kind == "weather_location" else (0,))
        )
    )
    waiter = getattr(client, f"_wait_for_{kind}")
    if success:
        result = await waiter(*args)
        assert (
            result is None
            if kind in {"radio_station", "weather_location"}
            else bool(result)
        )
    else:
        with pytest.raises(module.DHEError, match="timed out"):
            await waiter(*args)


async def test_catalog_timeout_can_reuse_known_catalogs(device, monkeypatch):
    client, _, _ = device
    media = sys.modules[f"{PACKAGE_NAME}.client_runtime_media"]
    monkeypatch.setattr(media, "WEATHER_CATALOG_TIMEOUT", 0)
    client._last_weather_countries = [{"CountryId": 34}]
    client._last_radio_catalogs["genre"] = ["Rock"]
    assert await client._wait_for_weather_countries(0) == [{"CountryId": 34}]
    assert await client._wait_for_radio_catalog("genre", 0) == ["Rock"]


async def test_weather_invalid_payloads_and_location_preserve_catalog_context(device):
    client, _, p = device
    for command in (
        p.WEATHER_COUNTRIES_SET_COMMAND,
        p.WEATHER_FAVORITES_SET_COMMAND,
        p.WEATHER_FORECAST_SET_COMMAND,
    ):
        client._handle_weather_value(command, None)
    assert (
        client._weather_countries_generation
        == client._weather_favorites_generation
        == client._weather_search_generation
        == 0
    )
    client._handle_weather_value(p.WEATHER_COUNTRY_SET_COMMAND, 34)
    client._handle_weather_value(
        p.WEATHER_FAVORITES_SET_COMMAND, [{"LocationId": "fixture"}]
    )
    client._handle_weather_value(
        p.WEATHER_FORECAST_SET_COMMAND, [{"LocationId": "fixture"}]
    )
    client._handle_weather_value(
        p.WEATHER_LOCATION_SET_COMMAND, {"Location": {"LocationId": "fixture"}}
    )
    assert client.last_weather_state["country_id"] == 34
    assert len(client.last_weather_state["favorites"]) == 1
    client._handle_weather_value(p.WEATHER_COUNTRY_SET_COMMAND, "bad")
    assert "country_id" not in client.last_weather_state
    client._handle_weather_value("set:ste.app.weather:unknown", "ignored")
    client._handle_weather_value(p.WEATHER_LOCATION_SET_COMMAND, None)
    assert client.last_weather_state == {}


async def test_dispatcher_records_app_commands_without_odb_side_effects(device):
    client, _, p = device
    cases = [
        (next(iter(p.APP_TIMER_RESET_COMMANDS)), None, "timer_reset"),
        (next(iter(p.RADIO_KNOWN_REQUEST_COMMANDS)), [], "radio_request"),
        (next(iter(p.RADIO_ASSIGN_COMMANDS)), [], "radio_assign"),
        (next(iter(p.WEATHER_ASSIGN_COMMANDS)), [], "weather_assign"),
    ]
    event_type = sys.modules[f"{PACKAGE_NAME}.client_types"].DHEEvent
    for command, value, category in cases:
        await client._handle_runtime_event(
            event_type("message", {"command": command, "value": value})
        )
        assert client._runtime_parser_stats[category] == 1


@pytest.mark.parametrize(
    "error", [OSError("disconnected"), RuntimeError("Session is closed")]
)
async def test_stale_runtime_probe_failure_requests_reconnect(
    device, monkeypatch, error
):
    client, module, _ = device
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: 10000))
    client._ready.set()
    client._last_message_monotonic = 1
    client._request_odb_value = AsyncMock(side_effect=error)
    await client._maybe_recover_stale_runtime(client._ctx)
    client._force_reconnect.assert_awaited_once()
    assert "probe failed" in client._force_reconnect.call_args.kwargs["reason"]
    assert client._stale_watchdog_probe_started_monotonic is None


async def test_pairing_failure_pauses_automatic_reconnect_until_stopped(device):
    client, _, _ = device
    ctx = client._ctx
    client._close_session = AsyncMock()
    client._pause_auto_reconnect_for_pairing = True
    background_tasks = []

    def create_task(coro, name):
        task = asyncio.create_task(coro, name=name)
        background_tasks.append(task)
        return task

    client.hass.async_create_background_task = create_task
    task = asyncio.create_task(
        client._handle_transport_reconnect(OSError("disconnected"))
    )
    try:
        await asyncio.sleep(0)
        assert not task.done()
        assert (
            client.diagnostic_state["connection_state"]
            == "pairing_failed_waiting_manual_retry"
        )
        assert not client.available
    finally:
        client._stopped.set()
        await task
        await asyncio.gather(*background_tasks, return_exceptions=True)
    assert task.result() is True
    assert all(task.done() for task in background_tasks)
    client._close_session.assert_awaited_once_with(ctx)
