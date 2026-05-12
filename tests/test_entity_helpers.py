"""Tests for shared Stiebel DHE entity helpers."""

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
    legacy_device_identifier: str | None = None


class TestEntityHelpers(unittest.TestCase):
    """Validate pure helper behavior without Home Assistant runtime imports."""

    def setUp(self) -> None:
        self.helpers = _load_entity_helpers()

    def test_build_entity_unique_id_uses_entry_prefix(self) -> None:
        self.assertEqual(
            self.helpers.build_entity_unique_id("entry-1", "setpoint"),
            "stiebel_dhe_connect_entry-1_setpoint",
        )

    def test_build_entry_signal_uses_entry_prefix(self) -> None:
        self.assertEqual(
            self.helpers.build_entry_signal("entry-1", "changed"),
            "stiebel_dhe_connect_entry-1_changed",
        )

    def test_build_device_info_uses_host_port_identifier(self) -> None:
        self.assertEqual(
            self.helpers.build_device_info("10.0.0.5", 8443, "Bathroom DHE"),
            {
                "identifiers": {("stiebel_dhe_connect", "10.0.0.5:8443")},
                "manufacturer": "STIEBEL ELTRON",
                "model": "DHE Connect",
                "name": "Bathroom DHE",
            },
        )

    def test_build_device_info_can_preserve_legacy_identifier(self) -> None:
        device_info = self.helpers.build_device_info(
            "10.0.0.5",
            9443,
            "Bathroom DHE",
            "10.0.0.5",
        )

        self.assertEqual(
            device_info["identifiers"],
            {
                ("stiebel_dhe_connect", "10.0.0.5"),
                ("stiebel_dhe_connect", "10.0.0.5:9443"),
            },
        )

    def test_entity_mixin_initializes_shared_identity(self) -> None:
        class DummyEntity(self.helpers.StiebelDHEEntityMixin):
            pass

        client = FakeClient(
            host="dhe.local",
            port=8443,
            legacy_device_identifier="dhe.local",
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
        self.assertEqual(
            entity._attr_device_info["identifiers"],
            {
                ("stiebel_dhe_connect", "dhe.local"),
                ("stiebel_dhe_connect", "dhe.local:8443"),
            },
        )


if __name__ == "__main__":
    unittest.main()
