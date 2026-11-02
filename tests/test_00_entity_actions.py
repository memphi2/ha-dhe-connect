"""Native HA entities: confirmed actions, restoration and failed device writes."""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import HomeAssistantError

from tests.ha_test_support import DOMAIN, _clear_loaded_integration_modules


@pytest.fixture
def platform():
    _clear_loaded_integration_modules()
    return SimpleNamespace(
        **{
            name: importlib.import_module(f"custom_components.{DOMAIN}.{name}")
            for name in (
                "switch",
                "text",
                "number",
                "binary_sensor",
                "media_player",
                "select",
                "climate",
            )
        }
    )


@pytest.fixture
def client():
    return SimpleNamespace(
        host="device.invalid",
        port=8443,
        available=True,
        last_setpoint=40,
        last_measurements={},
        _last_measurement_attributes={},
        last_device_info={},
        last_weather_state={},
        last_radio_state={},
        add_measurement_callback=Mock(return_value=Mock()),
        add_availability_callback=Mock(return_value=Mock()),
        add_wellness_programs_callback=Mock(return_value=Mock()),
    )


def prepare(entity):
    entity.async_write_ha_state = Mock()
    entity.async_on_remove = Mock()
    entity.async_get_last_state = AsyncMock(return_value=None)
    return entity


def make_switch(module, client, kind):
    cls, descriptions = {
        "odb": (module.StiebelDHEODBSwitch, module.ODB_SWITCHES),
        "timer": (module.StiebelDHEAppTimerSwitch, module.APP_TIMER_SWITCHES),
        "wellness": (
            module.StiebelDHEWellnessShowerProgramSwitch,
            module.WELLNESS_PROGRAM_SWITCHES,
        ),
    }[kind]
    return prepare(cls("entry", "Fixture", client, descriptions[0]))


@pytest.mark.parametrize("kind", ["odb", "timer", "wellness"])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("failure", [False, True])
async def test_switch_actions_update_only_from_successful_device_commands(
    platform, client, kind, enabled, failure
):
    module = platform.switch
    entity = make_switch(module, client, kind)
    description = entity.entity_description
    if kind == "odb":
        setter = description.turn_on_setter if enabled else description.turn_off_setter
        args = description.turn_on_args if enabled else description.turn_off_args
    elif kind == "timer":
        setter, args = description.setter, (enabled,)
    else:
        setter = (
            "set_wellness_shower_program" if enabled else "stop_wellness_shower_program"
        )
        args = (description.program_id,) if enabled else ()
    command = AsyncMock(
        return_value=enabled,
        side_effect=module.DHEError("no readback") if failure else None,
    )
    setattr(client, setter, command)
    action = entity.async_turn_on if enabled else entity.async_turn_off
    if failure:
        with pytest.raises(HomeAssistantError, match="Could not"):
            await action()
        assert entity.is_on is None
    else:
        await action()
        assert entity.is_on is enabled
        assert entity.available
    command.assert_awaited_once_with(*args)
    entity.async_write_ha_state.assert_called_once()


@pytest.mark.parametrize("kind", ["odb", "timer", "wellness"])
async def test_switch_restore_and_unrelated_updates(platform, client, kind):
    entity = make_switch(platform.switch, client, kind)
    entity.async_get_last_state.return_value = SimpleNamespace(state="on")
    await entity.async_added_to_hass()
    assert entity.is_on is True
    before = entity.async_write_ha_state.call_count
    entity._handle_measurement_update(-999, False)
    assert entity.async_write_ha_state.call_count == before
    if kind == "wellness":
        entity._handle_measurement_update(platform.switch.ID_WELLNESS_ACTIVE, False)
        entity._handle_measurement_update(
            platform.switch.ID_WELLNESS_SHOWER_PROGRAM,
            entity.entity_description.program_id,
        )
        assert entity.is_on is False
        entity._handle_measurement_update(platform.switch.ID_WELLNESS_ACTIVE, True)
        assert entity.is_on is True
        entity._handle_wellness_programs_update(
            (
                {
                    "id": entity.entity_description.program_id,
                    "name": "Fixture",
                    "coldwater": True,
                    "duration": 60,
                },
            )
        )
        assert entity.extra_state_attributes["program_name"] == "Cold prevention"
        assert entity.extra_state_attributes["heating_off_during_coldwater"] is True
    else:
        entity._handle_measurement_update(
            entity.entity_description.measurement_id, False
        )
        assert entity.is_on is False


@pytest.mark.parametrize("kind", ["memory", "controlunit"])
@pytest.mark.parametrize("cached", [False, True])
async def test_text_restore_prefers_device_metadata(platform, client, kind, cached):
    module = platform.text
    if kind == "memory":
        measurement = module.TEMPERATURE_MEMORY_MEASUREMENT_SLOT_ITEMS[0][0]
        entity = prepare(
            module.StiebelDHEText(
                "entry",
                "Fixture",
                client,
                module._temperature_memory_text_description(1, measurement),
            )
        )
        if cached:
            client._last_measurement_attributes[measurement] = {"name": "Device value"}
    else:
        entity = prepare(
            module.StiebelDHEControlUnitNameText("entry", "Fixture", client)
        )
        if cached:
            client.last_device_info["controlunit_name"] = "Device value"
    entity.async_get_last_state.return_value = SimpleNamespace(state="Restored value")
    await entity.async_added_to_hass()
    assert entity.native_value == ("Device value" if cached else "Restored value")
    assert entity.async_get_last_state.await_count == int(not cached)
    entity._handle_measurement_update(-999, None)
    entity.async_write_ha_state.assert_not_called()


@pytest.mark.parametrize("kind", ["memory", "controlunit"])
@pytest.mark.parametrize("failure", [False, True])
async def test_text_writes_keep_previous_value_on_failure(
    platform, client, kind, failure
):
    module = platform.text
    if kind == "memory":
        measurement = module.TEMPERATURE_MEMORY_MEASUREMENT_SLOT_ITEMS[0][0]
        entity = prepare(
            module.StiebelDHEText(
                "entry",
                "Fixture",
                client,
                module._temperature_memory_text_description(1, measurement),
            )
        )
        setter, args = "set_temperature_memory_name", (1, "New name")
    else:
        entity = prepare(
            module.StiebelDHEControlUnitNameText("entry", "Fixture", client)
        )
        setter, args = "set_controlunit_name", ("New name",)
    entity._attr_native_value = "Previous"
    command = AsyncMock(
        return_value="Confirmed name",
        side_effect=module.DHEError("no readback") if failure else None,
    )
    setattr(client, setter, command)
    if failure:
        with pytest.raises(HomeAssistantError, match="Could not"):
            await entity.async_set_value("New name")
        assert entity.native_value == "Previous"
    else:
        await entity.async_set_value("New name")
        assert entity.native_value == "Confirmed name"
    command.assert_awaited_once_with(*args)


NUMBER_CASES = [
    ("bath_fill_target_volume", "set_bath_fill_target_volume", 100, 100),
    ("child_safety_temperature_limit", "set_child_safety_temperature_limit", 42, 42),
    ("eco_flow_limit", "set_eco_flow_limit", 8, 8),
    ("brush_timer_duration", "set_brush_timer_duration_minutes", 120, 2),
    ("shower_timer_duration", "set_shower_timer_duration_minutes", 120, 2),
]


@pytest.mark.parametrize("key,setter,native,device_value", NUMBER_CASES)
@pytest.mark.parametrize("failure", [False, True])
async def test_number_actions_convert_units_and_preserve_failed_state(
    platform, client, key, setter, native, device_value, failure
):
    module = platform.number
    description = next(
        item for item in module.STATIC_NUMBER_DESCRIPTIONS if item.key == key
    )
    entity = prepare(
        module.StiebelDHENumber(
            SimpleNamespace(data={}, options={}),
            "entry",
            "Fixture",
            client,
            description,
        )
    )
    command = AsyncMock(
        return_value=device_value,
        side_effect=module.DHEError("no readback") if failure else None,
    )
    setattr(client, setter, command)
    if failure:
        with pytest.raises(HomeAssistantError, match="Could not"):
            await entity.async_set_native_value(native)
        assert entity.native_value is None
    else:
        await entity.async_set_native_value(native)
        assert entity.native_value == native
    command.assert_awaited_once_with(device_value)
    entity._handle_measurement_update(description.odb_id, "invalid")
    assert entity.native_value is None


@pytest.mark.parametrize(
    "key,restored",
    [("brush_timer_duration", 90), ("child_safety_temperature_limit", 42)],
)
async def test_number_restore_uses_native_units_not_device_units(
    platform, client, key, restored
):
    module = platform.number
    description = next(
        item for item in module.STATIC_NUMBER_DESCRIPTIONS if item.key == key
    )
    entity = prepare(
        module.StiebelDHENumber(
            SimpleNamespace(data={}, options={}),
            "entry",
            "Fixture",
            client,
            description,
        )
    )
    entity.async_get_last_number_data = AsyncMock(
        return_value=SimpleNamespace(native_value=restored)
    )
    await entity.async_added_to_hass()
    assert entity.native_value == restored
    assert entity._native_value_to_client("invalid") is None
    assert entity._restore_native_value("invalid") is None


@pytest.mark.parametrize(
    "action,setter,args",
    [
        ("async_turn_on", "set_radio_play", (True,)),
        ("async_media_pause", "set_radio_play", (False,)),
        ("async_turn_off", "set_radio_play", (False,)),
        ("async_set_volume_level", "set_radio_volume", (0.4,)),
        ("async_select_source", "select_radio_station", ({"Id": 1},)),
    ],
)
@pytest.mark.parametrize("failure", [False, True])
async def test_radio_actions_propagate_errors_and_confirm_success(
    platform, client, action, setter, args, failure
):
    module = platform.media_player
    entity = prepare(module.StiebelDHERadioMediaPlayer("entry", "Fixture", client))
    entity._sources_by_option = {"Fixture": {"Id": 1}}
    command = AsyncMock(
        return_value=args[0],
        side_effect=module.DHEError("no readback") if failure else None,
    )
    setattr(client, setter, command)
    input_args = (
        ("Fixture",)
        if action == "async_select_source"
        else ((0.4,) if action == "async_set_volume_level" else ())
    )
    if failure:
        with pytest.raises(HomeAssistantError, match="Could not"):
            await getattr(entity, action)(*input_args)
        entity.async_write_ha_state.assert_not_called()
    else:
        await getattr(entity, action)(*input_args)
        assert entity.available
        entity.async_write_ha_state.assert_called_once()
        if action == "async_turn_off":
            assert entity.state == module.MediaPlayerState.OFF
    command.assert_awaited_once_with(*args)


async def test_radio_next_previous_wrap_favorites_and_reject_empty_list(
    platform, client
):
    module = platform.media_player
    entity = prepare(module.StiebelDHERadioMediaPlayer("entry", "Fixture", client))
    with pytest.raises(HomeAssistantError, match="No DHE radio favorites"):
        await entity.async_media_next_track()
    client.select_radio_station = AsyncMock()
    entity._sources_by_option = {"One": {"Id": 1}, "Two": {"Id": 2}}
    await entity.async_media_previous_track()
    assert entity.source == "Two"
    await entity.async_media_next_track()
    assert entity.source == "One"
    entity._attr_source = None
    await entity.async_media_next_track()
    assert entity.source == "One"
    with pytest.raises(HomeAssistantError, match="Unknown DHE radio source"):
        await entity.async_select_source("Missing")


@pytest.mark.parametrize("failure", [False, True])
async def test_weather_select_known_unknown_and_device_failure(
    platform, client, failure
):
    module = platform.select
    entity = prepare(module.StiebelDHEWeatherLocationSelect("entry", "Fixture", client))
    with pytest.raises(HomeAssistantError, match="Unknown weather"):
        await entity.async_select_option("Missing")
    location = {"LocationId": "fixture", "Name": "Fixture"}
    entity._locations_by_option = {"Fixture": location}
    client.last_weather_state = {"location": location}
    client.select_weather_location = AsyncMock(
        side_effect=module.DHEError("no readback") if failure else None
    )
    if failure:
        with pytest.raises(HomeAssistantError, match="Could not"):
            await entity.async_select_option("Fixture")
        assert entity.current_option is None
    else:
        await entity.async_select_option("Fixture")
        assert entity.current_option == "Fixture"
    client.select_weather_location.assert_awaited_once_with(location)


@pytest.mark.parametrize(
    "action", ["async_turn_on", "async_turn_off", "async_set_temperature"]
)
async def test_climate_device_failure_is_a_translated_action_error(
    platform, client, action
):
    module = platform.climate
    entity = prepare(
        module.StiebelDHEClimate(
            SimpleNamespace(data={}, options={}), "entry", "Fixture", client
        )
    )
    client.set_water_heating_enabled = AsyncMock(
        side_effect=module.DHEError("no readback")
    )
    client.set_temperature = AsyncMock(side_effect=module.DHEError("no readback"))
    with pytest.raises(HomeAssistantError, match="Could not"):
        await getattr(entity, action)(
            **({"temperature": 40} if action == "async_set_temperature" else {})
        )
    entity.async_write_ha_state.assert_not_called()


@pytest.mark.parametrize("accepted", [False, True])
async def test_climate_enable_handles_failed_target_restore(
    platform, client, caplog, accepted
):
    module = platform.climate
    entity = prepare(
        module.StiebelDHEClimate(
            SimpleNamespace(data={}, options={}), "entry", "Fixture", client
        )
    )
    client.set_water_heating_enabled = AsyncMock(return_value=accepted)
    client.set_temperature = AsyncMock(side_effect=module.DHEError("no readback"))
    await entity.async_turn_on()
    assert entity.hvac_mode == (
        module.HVACMode.HEAT if accepted else module.HVACMode.OFF
    )
    assert client.set_temperature.await_count == int(accepted)
    assert (
        "restore previous target" in caplog.text
        if accepted
        else "after heating ON" in caplog.text
    )
    with pytest.raises(HomeAssistantError, match="Unsupported HVAC"):
        await entity.async_set_hvac_mode(module.HVACMode.COOL)
    assert entity._coerce_temperature("invalid") is None


async def test_climate_temperature_change_requires_successful_heating_enable(
    platform, client
):
    module = platform.climate
    entity = prepare(
        module.StiebelDHEClimate(
            SimpleNamespace(data={}, options={}), "entry", "Fixture", client
        )
    )
    entity._attr_hvac_mode = module.HVACMode.OFF
    client.set_water_heating_enabled = AsyncMock(return_value=False)
    client.set_temperature = AsyncMock()
    with pytest.raises(HomeAssistantError, match="Could not"):
        await entity.async_set_temperature(temperature=40)
    client.set_temperature.assert_not_awaited()
    await entity.async_set_temperature()
    with pytest.raises(HomeAssistantError, match="finite"):
        await entity.async_set_temperature(temperature=float("nan"))


async def test_wellness_switch_restores_latest_device_program(platform, client):
    module = platform.switch
    client.last_measurements = {
        module.ID_WELLNESS_ACTIVE: True,
        module.ID_WELLNESS_SHOWER_PROGRAM: 1,
    }
    entity = make_switch(module, client, "wellness")
    await entity.async_added_to_hass()
    assert entity.is_on is True
    entity.async_get_last_state.assert_not_awaited()


async def test_binary_sensor_cache_invalid_values_and_duplicate_suppression(
    platform, client
):
    module = platform.binary_sensor
    description = module.BINARY_SENSOR_DESCRIPTIONS[0]
    client.last_measurements[description.odb_id] = True
    entity = prepare(
        module.StiebelDHEBinarySensor("entry", "Fixture", client, description)
    )
    await entity.async_added_to_hass()
    assert entity.is_on is True
    entity._handle_measurement_update(-999, False)
    entity.async_write_ha_state.assert_not_called()
    entity._handle_measurement_update(description.odb_id, "invalid")
    assert entity.is_on is None
    assert not entity.available
    entity._handle_measurement_update(description.odb_id, False)
    assert entity.is_on is False
    entity._handle_availability_update(False)
    count = entity.async_write_ha_state.call_count
    entity._handle_availability_update(False)
    assert entity.async_write_ha_state.call_count == count


def test_weather_option_labels_are_unique_even_without_location_ids(platform):
    module = platform.select
    assert module._weather_location_labels([{"Name": "Fixture"}] * 3) == [
        "Fixture",
        "Fixture #2",
        "Fixture #3",
    ]
    assert module._base_weather_location_label({"LocationId": "fixture"}) == "fixture"
    assert module._option_for_location({"Name": "Unknown"}, {}) == "Unknown"
    assert (
        module._location_identifier({"Name": "Fixture", "CountryId": 34})
        == "34:Fixture"
    )
    assert module._location_identifier({"Name": "Fixture"}) == "Fixture"
