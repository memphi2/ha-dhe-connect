"""App payload parsing preserves valid state and rejects malformed updates."""

import sys
from unittest.mock import Mock

import pytest

from tests.client_behavior_support import make_client
from tests.client_test_support import PACKAGE_NAME


@pytest.fixture
async def device(monkeypatch):
    client, module = make_client(monkeypatch)
    return client, module, sys.modules[f"{PACKAGE_NAME}.protocol"]


@pytest.mark.parametrize("path_name", ["BRUSH_TIMER_PATH", "SHOWER_TIMER_PATH"])
async def test_timer_duration_remaining_activation_and_reset(device, path_name):
    client, _, p = device
    path = getattr(p, path_name)
    ids = p.TIMER_PATH_IDS[path]
    client._handle_app_timer_value(f"set:{path}:durationMilliseconds", 180000)
    client._handle_app_timer_value(f"set:{path}:remainingMilliseconds", 90000)
    client._handle_app_timer_value(f"set:{path}:activation", True)
    assert client.last_measurements[ids["durationMilliseconds"]] == 3
    assert client.last_measurements[ids["remainingMilliseconds"]] == 1.5
    client._handle_app_timer_reset(f"set:{path}:reset")
    assert client.last_measurements[ids["remainingMilliseconds"]] == 3
    assert client.last_measurements[ids["activation"]] is False
    client._last_measurements[ids["durationMilliseconds"]] = "bad"
    client._handle_app_timer_reset(f"set:{path}:reset")
    assert (
        client.last_measurements[ids["remainingMilliseconds"]]
        == p.TIMER_DEFAULT_DURATIONS[path]
    )
    before = dict(client.last_measurements)
    for command, value in [
        ("invalid", 1),
        (f"set:{path}:unknown", 1),
        (f"set:{path}:durationMilliseconds", "nan"),
    ]:
        client._handle_app_timer_value(command, value)
    client._handle_app_timer_reset("invalid")
    assert client.last_measurements == before


async def test_consumption_and_last_usage_ignore_bad_values_but_keep_valid_fields(
    device,
):
    client, _, p = device
    command, measurement = next(iter(p.CONSUMPTION_COMMAND_IDS.items()))
    for bad in (None, {"chart": {}}, {"chart": ["bad"]}):
        client._handle_consumption_value(command, bad)
    assert measurement not in client.last_measurements
    client._handle_consumption_value(command, {"chart": [1.2, 2.3], "sum": 0.5})
    assert client.last_measurements[measurement] == 3.5
    assert client._last_measurement_attributes[measurement]["cost_eur"] == 0.5
    client._handle_last_usage_value(None)
    client._handle_last_usage_value(
        {
            "water": {"value": 12.345, "min": "unknown", "max": 20},
            "energy": {"value": "bad"},
            "time": None,
        }
    )
    assert client.last_measurements[p.ID_LAST_USAGE_WATER] == 12.35
    assert p.ID_LAST_USAGE_ENERGY not in client.last_measurements
    assert (
        client._last_measurement_attributes[p.ID_LAST_USAGE_WATER]["min"] == "unknown"
    )


async def test_saving_monitor_activation_and_partial_payloads(device):
    client, _, p = device
    command = "set:ste.app.savingMonitor:ActivationRate"
    client._handle_saving_monitor_value(command, "bad")
    assert p.ID_SAVING_MONITOR_ACTIVATION_RATE not in client.last_measurements
    client._handle_saving_monitor_value(command, 12.34)
    assert client.last_measurements[p.ID_SAVING_MONITOR_ACTIVATION_RATE] == 12.3
    for bad in (None, {}, {"water_l": "bad"}):
        client._handle_saving_monitor_value("set:ste.app.savingMonitor:possible", bad)
    assert "possible" not in client._last_saving_monitor_values
    client._refresh_saving_monitor_sensors(category="unknown")
    client._refresh_saving_monitor_sensors()
    client._update_saving_monitor_sensor(9999, 1.0, "unknown", "unknown")
    assert client.last_measurements[9999] == 1


async def test_memory_updates_remove_stale_slots_and_reject_invalid_entries(device):
    client, _, p = device
    command = p.TEMP_MEMORY_SET_COMMAND
    client._handle_temperature_memory_value(
        [{"id": 0, "temperature": 40}, {"id": 1, "temperature": 42}],
        source_command=command,
    )
    client._handle_temperature_memory_value(
        [{"id": 1, "temperature": 43}], source_command=command
    )
    assert p.TEMPERATURE_MEMORY_ID_TO_MEASUREMENT[0] not in client.last_measurements
    assert client.last_measurements[p.TEMPERATURE_MEMORY_ID_TO_MEASUREMENT[1]] == 43
    for bad in (None, "bad", {}, {"id": "invalid"}, {"id": 99, "temperature": 42}):
        assert (
            client._handle_temperature_memory_item(bad, source_command=command) is None
        )
    for bad in ({}, {"id": "invalid"}):
        client._handle_temperature_memory_delete_item(bad, source_command=command)
    client._clear_temperature_memory(99, source_command=command)
    client._handle_temperature_memory_value(None, source_command=command)
    client._handle_temperature_memory_value(
        {"id": 1, "operation": "delete"}, source_command=command
    )
    assert not client._temperature_memory_ids_seen


async def test_device_metadata_removal_nested_contacts_and_boolean_fallback(device):
    client, _, _ = device
    prefix = "set:ste.common.version:"
    client._handle_device_info_value(prefix + "controlunitName", " Controller ")
    assert client.last_device_info["controlunit_name"] == "Controller"
    client._handle_device_info_value(prefix + "controlunitName", None)
    client._handle_device_info_value(prefix + "orderNumber", " ")
    assert "controlunit_name" not in client.last_device_info
    assert "order_number" not in client.last_device_info
    client._handle_device_info_value(
        prefix + "gadgetData", {"id": {"value": "fixture"}}
    )
    assert client.last_device_info["product_id_prefix"] == "fixture"
    client._handle_device_info_value(
        prefix + "gadgetDataValid", ["unsupported boolean"]
    )
    assert client.last_device_info["gadget_data_valid"] is True
    client._handle_device_info_value(
        prefix + "contactData",
        {"company": {"value": "Example"}, "mail": "support@example.invalid"},
    )
    assert client.last_device_info["service_contact"]["company"] == "Example"
    client._handle_device_info_value(prefix + "other", "fixture")
    assert client.last_device_info["other"] == "fixture"


async def test_override_and_startup_handlers_are_idempotent(device):
    client, _, p = device
    command = next(iter(p.TEMPERATURE_MAX_OVERRIDE_COMMANDS))
    client._handle_temperature_max_override_value("invalid", True)
    assert "temperature_max_override_active" not in client.diagnostic_state
    client._handle_temperature_max_override_value(command, ["unexpected"])
    assert client.diagnostic_state["temperature_max_override_active"] is True
    callback = Mock()
    client._wellness_program_callbacks.add(callback)
    client._handle_app_startup_value(p.WELLNESS_PROGRAMS_SET_COMMAND, [])
    callback.assert_not_called()
    client._handle_app_startup_value("set:ste.app:fixture", {"ready": True})
    assert client._last_app_values["set:ste.app:fixture"] == {"ready": True}
