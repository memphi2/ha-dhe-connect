"""Tests for shared DHE entity helpers."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ENTITY_HELPERS = (
    ROOT / "custom_components" / "stiebel_dhe_connect" / "entity_helpers.py"
)


def _load_entity_helpers():
    spec = importlib.util.spec_from_file_location("entity_helpers", ENTITY_HELPERS)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@dataclass
class FakeClient:
    host: str
    port: int
    device_identifier: str | None = None
    legacy_device_identifier: str | None = None
    legacy_device_identifiers: set[str] | None = None


class TestEntityHelpers(unittest.TestCase):
    """Validate pure helper behavior without Home Assistant runtime imports."""

    def setUp(self) -> None:
        self.helpers = _load_entity_helpers()

    def test_build_entity_unique_id_uses_entry_prefix(self) -> None:
        self.assertEqual(
            self.helpers.build_entity_unique_id("entry-1", "setpoint"),
            "stiebel_dhe_connect_entry-1_setpoint",
        )

    def test_build_entity_suggested_object_id_uses_device_name_and_key(self) -> None:
        self.assertEqual(
            self.helpers.build_entity_suggested_object_id("Bathroom DHE", "water_flow"),
            "Bathroom DHE_water_flow",
        )

    def test_build_entity_suggested_object_id_falls_back_to_domain(self) -> None:
        self.assertEqual(
            self.helpers.build_entity_suggested_object_id("", "water_flow"),
            "stiebel_dhe_connect_water_flow",
        )

    def test_temperature_memory_enabled_default_keeps_first_two_slots_enabled(
        self,
    ) -> None:
        self.assertTrue(self.helpers.temperature_memory_enabled_default(1))
        self.assertTrue(self.helpers.temperature_memory_enabled_default(2))
        self.assertFalse(self.helpers.temperature_memory_enabled_default(3))

    def test_temperature_memory_icon_uses_numeric_icon_for_visible_digits(self) -> None:
        self.assertEqual(
            self.helpers.temperature_memory_icon(1),
            "mdi:numeric-1-box-outline",
        )
        self.assertEqual(
            self.helpers.temperature_memory_icon(9),
            "mdi:numeric-9-box-outline",
        )

    def test_temperature_memory_icon_uses_counter_icon_for_two_digit_slots(
        self,
    ) -> None:
        self.assertEqual(self.helpers.temperature_memory_icon(10), "mdi:counter")

    def test_temperature_memory_measurement_slots_inverts_slot_mapping(self) -> None:
        self.assertEqual(
            self.helpers.temperature_memory_measurement_slots({1: 66, 2: 70}),
            {66: 1, 70: 2},
        )

    def test_temperature_memory_measurement_slot_items_are_sorted_by_slot(self) -> None:
        self.assertEqual(
            self.helpers.temperature_memory_measurement_slot_items({2: 70, 1: 66}),
            ((66, 1), (70, 2)),
        )

    def test_build_device_info_uses_stable_identifier_when_available(self) -> None:
        self.assertEqual(
            self.helpers.build_device_info(
                "192.0.2.5",
                8443,
                "Bathroom DHE",
                "device:aa:bb:cc:dd:ee:ff",
            ),
            {
                "identifiers": {
                    ("stiebel_dhe_connect", "device:aa:bb:cc:dd:ee:ff")
                },
                "model": "DHE Connect",
                "name": "Bathroom DHE",
            },
        )

    def test_build_device_info_falls_back_to_host_port_identifier(self) -> None:
        self.assertEqual(
            self.helpers.build_device_info("192.0.2.5", 8443, "Bathroom DHE"),
            {
                "identifiers": {("stiebel_dhe_connect", "192.0.2.5:8443")},
                "model": "DHE Connect",
                "name": "Bathroom DHE",
            },
        )

    def test_build_device_info_can_preserve_legacy_identifiers(self) -> None:
        device_info = self.helpers.build_device_info(
            "192.0.2.5",
            9443,
            "Bathroom DHE",
            "entry:abc",
            "192.0.2.5",
            {"192.0.2.5:8443"},
        )

        self.assertEqual(
            device_info["identifiers"],
            {
                ("stiebel_dhe_connect", "entry:abc"),
                ("stiebel_dhe_connect", "192.0.2.5"),
                ("stiebel_dhe_connect", "192.0.2.5:8443"),
            },
        )

    def test_entity_mixin_initializes_shared_identity(self) -> None:
        class DummyEntity(self.helpers.StiebelDHEEntityMixin):
            pass

        client = FakeClient(
            host="dhe.local",
            port=8443,
            device_identifier="device:aa:bb:cc:dd:ee:ff",
            legacy_device_identifier="dhe.local",
            legacy_device_identifiers={"192.0.2.5:8443"},
        )
        entity = DummyEntity()

        entity._init_dhe_entity(
            entry_id="entry-1",
            key="radio",
            name="Kitchen DHE",
            client=client,
        )

        self.assertIs(entity._client, client)
        self.assertEqual(entity._attr_unique_id, "stiebel_dhe_connect_entry-1_radio")
        self.assertEqual(entity._attr_suggested_object_id, "Kitchen DHE_radio")
        self.assertEqual(
            entity._attr_device_info["identifiers"],
            {
                ("stiebel_dhe_connect", "device:aa:bb:cc:dd:ee:ff"),
                ("stiebel_dhe_connect", "dhe.local"),
                ("stiebel_dhe_connect", "192.0.2.5:8443"),
            },
        )


if __name__ == "__main__":
    unittest.main()
