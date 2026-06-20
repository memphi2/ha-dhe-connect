"""Tests for canonical DHE wellness program metadata."""

from __future__ import annotations

import asyncio
import types
import unittest
from unittest.mock import AsyncMock, Mock

from homeassistant.helpers.typing import UNDEFINED

from custom_components.stiebel_dhe_connect.wellness_programs import (
    fallback_wellness_programs,
    normalize_wellness_programs,
    wellness_program_by_id,
)

try:
    from tests.test_client_weather_favorites import (
        _load_client,
        _load_component_module,
        _load_protocol,
    )
except ModuleNotFoundError:
    from test_client_weather_favorites import (  # type: ignore[no-redef]
        _load_client,
        _load_component_module,
        _load_protocol,
    )


class TestWellnessPrograms(unittest.TestCase):
    """Validate wellness catalog parsing and entity metadata."""

    def test_normalizes_live_wellness_catalog(self) -> None:
        programs = normalize_wellness_programs([
            {
                "id": "2",
                "name": "Wintererfrischung",
                "coldwater": False,
                "hot": "42.5",
                "cold": 32,
            },
            {
                "id": 1,
                "name": "Erkältungsvorbeugung",
                "coldwater": True,
            },
            {"id": 1, "name": "duplicate"},
            {"name": "invalid"},
        ])

        self.assertEqual([program["id"] for program in programs], [1, 2])
        self.assertEqual(programs[0]["name"], "Cold prevention")
        self.assertTrue(programs[0]["coldwater"])
        self.assertEqual(programs[1]["name"], "Winter pick-me-up")
        self.assertFalse(programs[1]["coldwater"])
        self.assertEqual(programs[1]["hot_temperature"], 42.5)
        self.assertEqual(programs[1]["cold_temperature"], 32.0)

    def test_unknown_or_missing_fields_keep_safe_fallback_metadata(self) -> None:
        programs = normalize_wellness_programs([
            {"id": 4, "name": "", "coldwater": "bad"},
        ])

        self.assertEqual(programs[0]["name"], "Circulation boost")
        self.assertTrue(programs[0]["coldwater"])
        self.assertEqual(
            wellness_program_by_id((), 3)["name"],
            "Summer fitness",
        )

    def test_runtime_stores_and_notifies_canonical_wellness_catalog(self) -> None:
        client_module = _load_client()
        protocol = _load_protocol()
        client = client_module.DHEClient.__new__(client_module.DHEClient)
        client._last_app_values = {}
        client._last_wellness_programs = ()
        updates: list[tuple[dict[str, object], ...]] = []
        client._wellness_program_callbacks = {updates.append}

        payload = [
            {"id": 1, "name": "Erkältungsvorbeugung", "coldwater": True},
            {"id": 2, "name": "Wintererfrischung", "coldwater": False},
        ]

        client_module.DHEClient._handle_app_startup_value(
            client,
            protocol.WELLNESS_PROGRAMS_SET_COMMAND,
            payload,
        )

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0][0]["name"], "Cold prevention")
        self.assertEqual(
            client._last_app_values[protocol.WELLNESS_PROGRAMS_SET_COMMAND],
            [dict(program) for program in client._last_wellness_programs],
        )

    def test_wellness_switch_uses_live_catalog_metadata(self) -> None:
        _load_component_module("client_types")
        _load_component_module("entity_helpers")
        _load_component_module("entity_state_helpers")
        _load_component_module("protocol")
        _load_component_module("runtime_helpers")
        _load_component_module("wellness_programs")
        switch_module = _load_component_module("switch")
        description = switch_module.WELLNESS_PROGRAM_SWITCHES[0]
        client = types.SimpleNamespace(
            host="dhe.local",
            port=8443,
            device_identifier=None,
        )
        entity = switch_module.StiebelDHEWellnessShowerProgramSwitch(
            entry_id="entry",
            name="DHE",
            client=client,
            description=description,
        )
        entity.async_write_ha_state = Mock()

        entity._handle_wellness_programs_update((
            {
                "id": 1,
                "name": "Erkältungsvorbeugung",
                "coldwater": True,
                "hot_temperature": 42.0,
                "cold_temperature": 20.0,
            },
        ))

        self.assertEqual(entity._attr_translation_key, "wellness_cold_prevention")
        self.assertEqual(
            entity._attr_extra_state_attributes["program_name"],
            "Cold prevention",
        )
        self.assertTrue(entity._attr_extra_state_attributes["coldwater"])
        self.assertTrue(
            entity._attr_extra_state_attributes["heating_off_during_coldwater"]
        )
        self.assertEqual(entity._attr_extra_state_attributes["hot_temperature"], 42.0)
        self.assertEqual(entity._attr_extra_state_attributes["cold_temperature"], 20.0)
        entity.async_write_ha_state.assert_called_once()

        entity._handle_wellness_programs_update((
            {
                "id": 1,
                "name": "Erkältungsvorbeugung",
                "coldwater": True,
                "hot_temperature": 42.0,
                "cold_temperature": 20.0,
            },
        ))

        entity.async_write_ha_state.assert_called_once()

    def test_odb_switch_suppresses_redundant_state_writes(self) -> None:
        _load_component_module("client_types")
        _load_component_module("entity_helpers")
        _load_component_module("entity_state_helpers")
        _load_component_module("protocol")
        _load_component_module("runtime_helpers")
        _load_component_module("wellness_programs")
        switch_module = _load_component_module("switch")
        description = switch_module.ODB_SWITCHES[0]
        client = types.SimpleNamespace(
            host="dhe.local",
            port=8443,
            device_identifier=None,
            available=True,
        )
        entity = switch_module.StiebelDHEODBSwitch(
            entry_id="entry",
            name="DHE",
            client=client,
            description=description,
        )
        entity.async_write_ha_state = Mock()

        entity._handle_measurement_update(description.measurement_id, 1)
        entity._handle_measurement_update(description.measurement_id, 1)
        entity._handle_measurement_update(description.measurement_id, 0)

        self.assertEqual(entity.async_write_ha_state.call_count, 2)

    def test_odb_switch_writes_cached_startup_measurement_after_availability(
        self,
    ) -> None:
        _load_component_module("client_types")
        _load_component_module("entity_helpers")
        _load_component_module("entity_state_helpers")
        _load_component_module("protocol")
        _load_component_module("runtime_helpers")
        _load_component_module("wellness_programs")
        switch_module = _load_component_module("switch")
        description = switch_module.ODB_SWITCHES[0]

        class _Client:
            host = "dhe.local"
            port = 8443
            device_identifier = None
            available = True
            last_measurements = {description.measurement_id: 1}

            def add_measurement_callback(self, _callback, *, replay=True):
                self.measurement_replay = replay
                return lambda: None

            def add_availability_callback(self, callback):
                callback(True)
                return lambda: None

        client = _Client()
        entity = switch_module.StiebelDHEODBSwitch(
            entry_id="entry",
            name="DHE",
            client=client,
            description=description,
        )
        entity.async_on_remove = lambda _remove: None
        entity.async_get_last_state = AsyncMock(return_value=None)
        entity.async_write_ha_state = Mock()

        asyncio.run(entity.async_added_to_hass())

        self.assertFalse(client.measurement_replay)
        self.assertTrue(entity._attr_is_on)
        self.assertTrue(entity._attr_available)
        self.assertEqual(entity.async_write_ha_state.call_count, 2)

    def test_binary_sensor_suppresses_redundant_state_writes(self) -> None:
        _load_component_module("client_types")
        _load_component_module("entity_helpers")
        _load_component_module("entity_state_helpers")
        _load_component_module("protocol")
        _load_component_module("runtime_helpers")
        binary_sensor_module = _load_component_module("binary_sensor")
        description = binary_sensor_module.BINARY_SENSOR_DESCRIPTIONS[0]
        client = types.SimpleNamespace(
            host="dhe.local",
            port=8443,
            device_identifier=None,
            available=True,
            last_measurements={},
            _last_measurement_attributes={},
        )
        entity = binary_sensor_module.StiebelDHEBinarySensor(
            entry_id="entry",
            name="DHE",
            client=client,
            description=description,
        )
        entity.async_write_ha_state = Mock()

        entity._handle_measurement_update(description.odb_id, 1)
        entity._handle_measurement_update(description.odb_id, 1)
        entity._handle_measurement_update(description.odb_id, 0)

        self.assertEqual(entity.async_write_ha_state.call_count, 2)

    def test_button_suppresses_redundant_availability_writes(self) -> None:
        _load_component_module("client_types")
        _load_component_module("entity_helpers")
        _load_component_module("entity_state_helpers")
        _load_component_module("protocol")
        _load_component_module("runtime_helpers")
        button_module = _load_component_module("button")
        description = button_module.STATIC_BUTTON_DESCRIPTIONS[0]
        client = types.SimpleNamespace(
            host="dhe.local",
            port=8443,
            device_identifier=None,
            available=True,
            last_measurements={},
        )
        entity = button_module.StiebelDHEButton(
            entry_id="entry",
            name="DHE",
            client=client,
            description=description,
        )
        entity.async_write_ha_state = Mock()

        entity._handle_measurement_update(description.availability_measurement_id, 1)
        entity._handle_measurement_update(description.availability_measurement_id, 1)
        entity._handle_availability_update(True)
        entity._handle_availability_update(False)

        self.assertEqual(entity.async_write_ha_state.call_count, 2)

    def test_wellness_switch_descriptions_match_fallback_catalog(self) -> None:
        _load_component_module("client_types")
        _load_component_module("entity_helpers")
        _load_component_module("entity_state_helpers")
        _load_component_module("protocol")
        _load_component_module("runtime_helpers")
        _load_component_module("wellness_programs")
        switch_module = _load_component_module("switch")

        fallback_programs = fallback_wellness_programs()
        descriptions = switch_module.WELLNESS_PROGRAM_SWITCHES

        self.assertEqual(
            [description.program_id for description in descriptions],
            [int(program["id"]) for program in fallback_programs],
        )
        self.assertEqual(
            [description.key for description in descriptions],
            [program["key"] for program in fallback_programs],
        )
        self.assertEqual(
            [description.translation_key for description in descriptions],
            [program["key"] for program in fallback_programs],
        )
        self.assertTrue(all(description.name is UNDEFINED for description in descriptions))

    def test_restored_timer_switch_value_stays_unavailable_offline(self) -> None:
        _load_component_module("client_types")
        _load_component_module("entity_helpers")
        _load_component_module("entity_state_helpers")
        _load_component_module("protocol")
        _load_component_module("runtime_helpers")
        _load_component_module("wellness_programs")
        switch_module = _load_component_module("switch")
        description = switch_module.APP_TIMER_SWITCHES[0]

        class _OfflineClient:
            host = "dhe.local"
            port = 8443
            device_identifier = None
            available = False
            last_measurements = {}

            def add_measurement_callback(self, _callback, *, replay=True):
                return lambda: None

            def add_availability_callback(self, _callback):
                return lambda: None

        entity = switch_module.StiebelDHEAppTimerSwitch(
            entry_id="entry",
            name="DHE",
            client=_OfflineClient(),
            description=description,
        )
        entity.async_on_remove = lambda _remove: None
        entity.async_get_last_state = AsyncMock(
            return_value=types.SimpleNamespace(state="off")
        )
        entity.async_write_ha_state = Mock()

        asyncio.run(entity.async_added_to_hass())

        self.assertFalse(entity._attr_is_on)
        self.assertFalse(entity._attr_available)
        entity.async_write_ha_state.assert_called_once()


if __name__ == "__main__":
    unittest.main()
