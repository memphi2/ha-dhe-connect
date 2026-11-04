"""Temperature memory operations must be confirmed by fresh device readback."""

import json
import sys
from unittest.mock import AsyncMock

import pytest

from tests.client_behavior_support import make_client
from tests.client_test_support import PACKAGE_NAME


@pytest.fixture
async def device(monkeypatch):
    client, module = make_client(monkeypatch)
    return client, module, sys.modules[f"{PACKAGE_NAME}.protocol"]


def memory_readbacks(client, protocol, *values):
    pending = iter(values)

    async def request(_ctx, command):
        assert command == protocol.TEMP_MEMORY_GET_COMMAND
        client._handle_temperature_memory_value(
            next(pending), source_command=protocol.TEMP_MEMORY_SET_COMMAND
        )

    client._request_app_value.side_effect = request


@pytest.mark.parametrize(
    "method,argument",
    [("set_temperature_memory", 42.5), ("set_temperature_memory_name", " Example ")],
)
async def test_memory_writes_roundtrip_and_keep_other_fields(device, method, argument):
    client, _, protocol = device
    initial = {"id": 0, "name": "Before", "temperature": 40.0}
    expected = (
        {**initial, "temperature": 42.5}
        if isinstance(argument, float)
        else {**initial, "name": "Example"}
    )
    memory_readbacks(client, protocol, [initial], [expected])
    result = await getattr(client, method)(1, argument)
    assert result == (42.5 if isinstance(argument, float) else "Example")
    packet = client._post_packet.call_args.args[1]
    payload = json.loads(packet[packet.index("[") :])[1]
    assert payload["command"] == protocol.TEMP_MEMORY_ASSIGN_COMMAND
    assert payload["value"]["name"] == expected["name"]
    assert payload["value"]["temperature"] == expected["temperature"]
    assert client._temperature_memory_generation == 2


@pytest.mark.parametrize(
    "exists,deleted", [(True, True), (True, False), (False, False)]
)
async def test_memory_delete_requires_existing_slot_and_confirmed_removal(
    device, exists, deleted
):
    client, module, protocol = device
    initial = [{"id": 0, "temperature": 40}]
    # Failure paths are retried once, and must still observe the same device state.
    memory_readbacks(
        client,
        protocol,
        *(initial if exists and not (deleted and i % 2) else [] for i in range(4)),
    )
    if exists and deleted:
        assert await client.delete_temperature_memory(1)
        assert (
            protocol.TEMPERATURE_MEMORY_SLOT_MEASUREMENTS[1]
            not in client.last_measurements
        )
    else:
        with pytest.raises(module.DHEError, match="not deleted|not available"):
            await client.delete_temperature_memory(1)
        if not exists:
            client._post_packet.assert_not_awaited()


@pytest.mark.parametrize("cached", [False, True])
async def test_memory_button_uses_slot_temperature_even_without_setpoint_ack(
    device, cached
):
    client, module, protocol = device
    values = [{"id": 0, "temperature": 41.5}]
    if cached:
        client._handle_temperature_memory_value(
            values, source_command=protocol.TEMP_MEMORY_SET_COMMAND
        )
    else:
        memory_readbacks(client, protocol, values)
    client._request_setpoint = AsyncMock(side_effect=module.DHEError("ack unavailable"))
    assert await client.press_temperature_memory(1)
    packet = client._post_packet.call_args.args[1]
    payload = json.loads(packet[packet.index("[") :])[1]
    assert payload["command"] == protocol.ODB_ASSIGN_COMMAND
    assert payload["value"]["id"] == protocol.ID_SETPOINT_REQUEST
    assert client._request_app_value.await_count == int(not cached)


@pytest.mark.parametrize(
    "method,args",
    [
        ("press_temperature_memory", [99]),
        ("set_temperature_memory", [99, 40]),
        ("set_temperature_memory_name", [1, " "]),
    ],
)
async def test_invalid_memory_input_never_writes(device, method, args):
    client, module, _ = device
    with pytest.raises(module.DHEError):
        await getattr(client, method)(*args)
    client._post_packet.assert_not_awaited()


async def test_memory_cache_and_sequential_creation_rules(device, monkeypatch):
    client, module, protocol = device
    memory_module = sys.modules[f"{PACKAGE_NAME}.client_temperature_memory_commands"]
    measurement = protocol.TEMPERATURE_MEMORY_SLOT_MEASUREMENTS[1]
    for value in (None, True):
        client._last_measurements[measurement] = value
        assert client._cached_temperature_memory_temperature(measurement) is None
    assert client._can_create_temperature_memory(0)
    assert not client._can_create_temperature_memory(1)
    client._temperature_memory_ids_seen = {0, 1}
    assert client._can_create_temperature_memory(2)
    client._temperature_memory_ids_seen = set(
        range(protocol.TEMPERATURE_MEMORY_MAX_SLOTS)
    )
    assert not client._can_create_temperature_memory(
        protocol.TEMPERATURE_MEMORY_MAX_SLOTS
    )
    monkeypatch.setattr(memory_module, "APP_COMMAND_CONFIRMATION_TIMEOUT", 0)
    with pytest.raises(module.DHEError, match="not available yet"):
        await client._get_temperature_memory_temperature(client._ctx, 1, measurement)
    await client._refresh_temperature_memories(client._ctx)
