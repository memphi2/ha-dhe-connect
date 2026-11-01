"""Real Home Assistant integration regression tests."""

from __future__ import annotations

import importlib
import threading
import types
from collections import Counter
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import loader
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
)
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)

from tests.ha_test_support import (
    DEFAULT_PORT,
    DOMAIN,
    _assert_entry_setup_and_unload,
    _async_test_home_assistant,
    _build_mock_entry,
    _clear_loaded_integration_modules,
    _entity_id_for_key,
    _FixtureDHEClient,
    _isolate_discovery_cache,  # noqa: F401 - registers the pytest fixture
)

pytestmark = pytest.mark.asyncio


async def test_fixture_uses_real_executor_threads() -> None:
    """Keep file I/O and import work off the HA event-loop thread in tests."""
    async with _async_test_home_assistant() as hass:
        loop_thread = threading.get_ident()
        assert await hass.async_add_executor_job(threading.get_ident) != loop_thread
        assert await hass.async_add_import_executor_job(threading.get_ident) != loop_thread



async def test_entity_id_changes_keep_subscriptions_and_native_climate_state(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Rename live entities with balanced callbacks and correct temperature units."""
    from homeassistant.helpers import entity_platform
    from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    from homeassistant.helpers.entity import Entity

    for module_name in (
        "binary_sensor", "button", "climate", "media_player", "number", "select",
        "sensor", "sensor_diagnostics", "switch", "text", "weather",
    ):
        module = importlib.import_module(f"custom_components.{DOMAIN}.{module_name}")
        for cls in vars(module).values():
            if (
                isinstance(cls, type) and issubclass(cls, Entity)
                and cls.__module__ == module.__name__
                and integration.HA_2026_11
            ):
                from homeassistant.helpers.entity import _entity_class_requires_readd

                assert not _entity_class_requires_readd(cls), cls.__name__
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host, port=client.port, name="Rename DHE", unique_id="rename-dhe"
        )
        entry.add_to_hass(hass)
        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        entities = [
            entity
            for platform in entity_platform.async_get_platforms(hass, DOMAIN)
            for entity in platform.entities.values()
        ]
        assert entities
        callbacks = {key: Counter(value) for key, value in client.callbacks.items()}
        registry = er.async_get(hass)
        for index, entity in enumerate(entities):
            for suffix in ("renamed", "renamed_again"):
                old_id = entity.entity_id
                new_id = f"{old_id.rsplit('.', 1)[0]}.{suffix}_{index}"
                with (
                    patch.object(entity, "async_added_to_hass", wraps=entity.async_added_to_hass) as added,
                    patch.object(entity, "async_will_remove_from_hass", wraps=entity.async_will_remove_from_hass) as removed,
                ):
                    registry.async_update_entity(old_id, new_entity_id=new_id)
                    await hass.async_block_till_done()
                    if integration.HA_2026_11:
                        added.assert_not_awaited()
                        removed.assert_not_awaited()
                    else:
                        added.assert_awaited_once()
                        removed.assert_awaited_once()
                assert entity.entity_id == new_id
                assert hass.states.get(old_id) is None
                assert hass.states.get(new_id) is not None
        assert {key: Counter(value) for key, value in client.callbacks.items()} == callbacks

        climate = next(entity for entity in entities if entity.entity_id.startswith("climate."))
        from homeassistant.const import UnitOfTemperature

        if integration.HA_2026_11:
            assert climate.native_temperature_unit == UnitOfTemperature.CELSIUS
            assert climate.native_current_temperature is None
        else:
            assert climate.temperature_unit == UnitOfTemperature.CELSIUS
            assert climate.current_temperature is None
        assert not any(
            key in climate.__dict__
            for key in ("_attr_temperature_unit", "_attr_target_temperature", "_attr_current_temperature")
        )
        hass.config.units = US_CUSTOMARY_SYSTEM
        for callback_fn in tuple(client.callbacks["setpoint"]):
            callback_fn(40.0)
        await hass.async_block_till_done()
        state = hass.states.get(climate.entity_id)
        assert state is not None
        assert state.attributes["temperature"] == 104.0
        if integration.HA_2026_11:
            assert state.attributes["temperature_unit"] == UnitOfTemperature.FAHRENHEIT
        else:
            assert hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT
        assert climate._attr_native_target_temperature == 40.0
        await hass.services.async_call(
            "climate", "set_temperature",
            {"entity_id": climate.entity_id, "temperature": 100.4}, blocking=True,
        )
        assert client.temperature_calls[-1] == pytest.approx(38.0)
        assert not any(
            "deprecated" in record.message.lower()
            and record.name.startswith(f"custom_components.{DOMAIN}")
            for record in caplog.records
        )
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert all(not value for value in client.callbacks.values())



async def test_unload_failure_keeps_runtime_and_raises_config_entry_error() -> None:
    """A failed platform unload must not stop the still-loaded client."""
    from homeassistant.exceptions import ConfigEntryError

    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    client = types.SimpleNamespace(stop=AsyncMock())
    runtime = types.SimpleNamespace(client=client, start_task=None)
    entry = types.SimpleNamespace(runtime_data=runtime)
    hass = types.SimpleNamespace(
        config_entries=types.SimpleNamespace(async_unload_platforms=AsyncMock(return_value=False))
    )
    if integration.HA_2026_11:
        with pytest.raises(ConfigEntryError, match="Could not unload"):
            await integration.async_unload_entry(hass, entry)
    else:
        assert await integration.async_unload_entry(hass, entry) is False
    assert entry.runtime_data is runtime
    client.stop.assert_not_awaited()



async def test_entry_setup_and_unload_with_real_hass_fixture() -> None:
    """Set up and unload the integration through HA's ConfigEntries manager."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        await _assert_entry_setup_and_unload(hass, integration)



async def test_entry_setup_raises_not_ready_when_target_unreachable() -> None:
    """Do not set up platforms until the configured DHE endpoint responds."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="offline-dhe.local",
            port=DEFAULT_PORT,
            name="Offline Fixture DHE",
            unique_id="offline-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with patch.object(
            integration,
            "_async_can_connect",
            AsyncMock(return_value=False),
        ), pytest.raises(ConfigEntryNotReady):
            await integration.async_setup_entry(hass, entry)



async def test_entry_setup_falls_back_to_original_data_target() -> None:
    """Use original Zeroconf IP data if an option hostname cannot be reached."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient(host="192.0.2.124", port=DEFAULT_PORT)
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Fallback Fixture DHE",
            unique_id="fallback-fixture-dhe",
        )
        entry.add_to_hass(hass)
        hass.config_entries.async_update_entry(
            entry,
            options={
                CONF_HOST: "dhe-ja06.local",
                CONF_PORT: DEFAULT_PORT,
                CONF_NAME: "Fallback Fixture DHE",
            },
        )

        can_connect = AsyncMock(side_effect=[False, True])
        with (
            patch.object(integration, "DHEClient", return_value=client) as client_cls,
            patch.object(integration, "_async_can_connect", can_connect),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        assert can_connect.await_args_list[0].args == (
            hass,
            "dhe-ja06.local",
            DEFAULT_PORT,
        )
        assert can_connect.await_args_list[1].args == (
            hass,
            "192.0.2.124",
            DEFAULT_PORT,
        )
        assert client_cls.call_args.kwargs["host"] == "192.0.2.124"
        assert client.start_called

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()



async def test_entry_reload_restarts_client_with_real_hass_fixture() -> None:
    """Reload through HA and assert runtime cleanup/startup remains balanced."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        first_client = _FixtureDHEClient()
        second_client = _FixtureDHEClient(last_setpoint=41.0)
        entry = _build_mock_entry(
            host=first_client.host,
            port=first_client.port,
            name="Reload Fixture DHE",
            unique_id="reload-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(
                integration,
                "DHEClient",
                side_effect=[first_client, second_client],
            ),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            assert await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()

        assert first_client.stop_called
        assert second_client.start_called
        assert entry.state is ConfigEntryState.LOADED
        assert entry.runtime_data.client is second_client
        assert hass.services.has_service(DOMAIN, "search_weather_location")

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert second_client.stop_called
        assert not hass.services.has_service(DOMAIN, "search_weather_location")



async def test_token_only_config_entry_update_does_not_reload_entry() -> None:
    """Persisting a refreshed token must not restart an otherwise loaded entry."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with _async_test_home_assistant() as hass:
        entry = _build_mock_entry(
            host="token-reload.local",
            port=DEFAULT_PORT,
            name="Token Reload Fixture DHE",
            unique_id="token-reload-fixture-dhe",
        )
        entry.add_to_hass(hass)
        runtime = integration.DHEConnectRuntimeData(
            client=_FixtureDHEClient(),
            name=entry.title,
            entry_reload_signature=integration._entry_reload_signature(entry),
        )
        integration.set_runtime_data(entry, runtime)

        hass.config_entries.async_update_entry(
            entry,
            data={
                **dict(entry.data),
                "token": "updated-token-value-0001",
            },
        )
        reload_entry = AsyncMock(return_value=True)
        with patch.object(hass.config_entries, "async_reload", reload_entry):
            await integration._async_update_listener(hass, entry)

        reload_entry.assert_not_awaited()



async def test_runtime_relevant_config_entry_update_reloads_entry() -> None:
    """Changing runtime data still reloads a loaded entry."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with _async_test_home_assistant() as hass:
        entry = _build_mock_entry(
            host="reload-old.local",
            port=DEFAULT_PORT,
            name="Reload Old Fixture DHE",
            unique_id="reload-old-fixture-dhe",
        )
        entry.add_to_hass(hass)
        runtime = integration.DHEConnectRuntimeData(
            client=_FixtureDHEClient(),
            name=entry.title,
            entry_reload_signature=integration._entry_reload_signature(entry),
        )
        integration.set_runtime_data(entry, runtime)

        hass.config_entries.async_update_entry(
            entry,
            data={
                **dict(entry.data),
                CONF_HOST: "reload-new.local",
            },
        )
        reload_entry = AsyncMock(return_value=True)
        with patch.object(hass.config_entries, "async_reload", reload_entry):
            await integration._async_update_listener(hass, entry)

        reload_entry.assert_awaited_once_with(entry.entry_id)



async def test_runtime_device_info_updates_ha_device_model_and_firmware() -> None:
    """Update manufacturer/model/firmware without replacing an existing device."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    protocol = importlib.import_module(f"custom_components.{DOMAIN}.protocol")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient(host="dhe-ja06.local", port=DEFAULT_PORT)
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Device Info Fixture DHE",
            unique_id="device-info-fixture-dhe",
        )
        entry.add_to_hass(hass)
        device_registry = dr.async_get(hass)
        existing_device = device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"device:{entry.unique_id}")},
            name=entry.title,
            model="DHE Connect",
        )
        assert existing_device.manufacturer is None
        device_registry.async_update_device(
            existing_device.id, name_by_user="User-assigned DHE"
        )

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
        assert len(devices) == 1
        assert devices[0].id == existing_device.id
        assert devices[0].name_by_user == "User-assigned DHE"
        assert devices[0].model == "DHE Connect"
        assert devices[0].manufacturer == "Stiebel Eltron"
        assert devices[0].sw_version is None
        entity_ids = {
            entity.unique_id: entity.entity_id
            for entity in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        }

        client.last_device_info = {
            "device_type": "DHE Connect 18/21/24",
            "protocol_version": "1.9.00",
            "raw_odb_protocol_version": 1,
        }
        client.emit_measurement(protocol.ID_DEVICE_INFO, "DHE Connect 18/21/24")
        await hass.async_block_till_done()

        devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
        assert len(devices) == 1
        assert devices[0].id == existing_device.id
        assert devices[0].identifiers == existing_device.identifiers
        assert devices[0].name_by_user == "User-assigned DHE"
        assert devices[0].model == "DHE Connect 18/21/24"
        assert devices[0].manufacturer == "Stiebel Eltron"
        assert devices[0].sw_version == "1.9.00"
        assert entity_ids == {
            entity.unique_id: entity.entity_id
            for entity in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        }

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()



async def test_bridge_temperature_maximum_button_calls_client_when_enabled_with_real_hass_fixture() -> None:
    """Verify bridge-max button uses child-safety state as lock signal."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    protocol = importlib.import_module(f"custom_components.{DOMAIN}.protocol")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Bridge Maximum Fixture DHE",
            unique_id="bridge-maximum-fixture-dhe",
        )
        entry.add_to_hass(hass)

        registry = er.async_get(hass)
        registry.async_get_or_create(
            "button",
            DOMAIN,
            f"{DOMAIN}_{entry.entry_id}_bridge_temperature_maximum",
            suggested_object_id="bridge_maximum_fixture_dhe_bridge_temperature_maximum",
            disabled_by=None,
        )

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        bridge_button = _entity_id_for_key(
            hass,
            entry.entry_id,
            "button",
            "bridge_temperature_maximum",
        )
        state = hass.states.get(bridge_button)
        assert state is not None
        assert state.state != "unavailable"

        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": bridge_button},
            blocking=True,
        )
        assert client.bridge_temperature_maximum_calls == 1

        client.emit_measurement(protocol.ID_CHILD_SAFETY_ACTIVE, False)
        await hass.async_block_till_done()
        state = hass.states.get(bridge_button)
        assert state is not None
        assert state.state == "unavailable"

        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": bridge_button},
            blocking=True,
        )
        assert client.bridge_temperature_maximum_calls == 1

        client.emit_measurement(protocol.ID_CHILD_SAFETY_ACTIVE, True)
        await hass.async_block_till_done()
        state = hass.states.get(bridge_button)
        assert state is not None
        assert state.state != "unavailable"

        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": bridge_button},
            blocking=True,
        )
        assert client.bridge_temperature_maximum_calls == 2

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()



async def test_entity_registry_ids_survive_reload_with_real_hass_fixture() -> None:
    """Reload an entry and verify HA keeps the same entity registry IDs."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        first_client = _FixtureDHEClient()
        second_client = _FixtureDHEClient(last_setpoint=41.0)
        entry = _build_mock_entry(
            host=first_client.host,
            port=first_client.port,
            name="Stable Fixture DHE",
            unique_id="stable-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(
                integration,
                "DHEClient",
                side_effect=[first_client, second_client],
            ),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            registry = er.async_get(hass)
            before = {
                entity.unique_id: entity.entity_id
                for entity in er.async_entries_for_config_entry(
                    registry,
                    entry.entry_id,
                )
            }

            assert await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()
            after = {
                entity.unique_id: entity.entity_id
                for entity in er.async_entries_for_config_entry(
                    registry,
                    entry.entry_id,
                )
            }

        assert before
        assert before == after
        assert first_client.stop_called
        assert second_client.start_called

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()



async def test_runtime_callbacks_update_sensor_states_with_real_hass_fixture() -> None:
    """Verify runtime callbacks update real HA sensor entities."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    protocol = importlib.import_module(f"custom_components.{DOMAIN}.protocol")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Runtime Fixture DHE",
            unique_id="runtime-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        water_flow_entity = _entity_id_for_key(hass, entry.entry_id, "sensor", "water_flow")
        reconnect_entity = _entity_id_for_key(
            hass,
            entry.entry_id,
            "sensor",
            "reconnect_count",
        )
        connection_state_entity = _entity_id_for_key(
            hass,
            entry.entry_id,
            "sensor",
            "connection_state",
        )

        client.emit_measurement(protocol.ID_WATER_FLOW, 7.5)
        client.emit_reconnect(3)
        client.emit_diagnostic({
            "connection_state": "reconnecting",
            "last_reconnect_reason": "fixture reconnect",
        })
        await hass.async_block_till_done()

        water_flow_state = hass.states.get(water_flow_entity)
        reconnect_state = hass.states.get(reconnect_entity)
        connection_state = hass.states.get(connection_state_entity)

        assert water_flow_state is not None
        assert water_flow_state.state == "7.5"
        assert reconnect_state is not None
        assert reconnect_state.state == "3"
        assert connection_state is not None
        assert connection_state.state == "reconnecting"

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()



async def test_availability_updates_climate_state_with_real_hass_fixture() -> None:
    """Verify runtime availability callbacks update HA entity state."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Availability Fixture DHE",
            unique_id="availability-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        entity_id = "climate.availability_fixture_dhe_water_heating"
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state != "unavailable"

        client.emit_availability(False)
        await hass.async_block_till_done()
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state == "unavailable"

        client.emit_availability(True)
        await hass.async_block_till_done()
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state != "unavailable"
        assert state.attributes["connection_state"] == "connected"

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
