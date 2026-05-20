"""Tests for user-visible translation labels."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS = ROOT / "custom_components" / "stiebel_dhe_connect" / "translations"


def _sensor_name(locale: str, key: str) -> str:
    data = json.loads((TRANSLATIONS / f"{locale}.json").read_text(encoding="utf-8"))
    return str(data["entity"]["sensor"][key]["name"])


class TestTranslations(unittest.TestCase):
    """Validate important entity labels."""

    def test_legacy_odb_translation_keys_are_not_reused(self) -> None:
        data = json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8"))
        sensor_keys = set(data["entity"]["sensor"])

        self.assertFalse(
            sensor_keys
            & {
                "hot_water_volume_total",
                "heating_energy_total",
                "possible_energy_saving",
                "possible_water_saving",
            },
        )

    def test_odb_saving_labels_are_explicit(self) -> None:
        self.assertEqual(
            _sensor_name("en", "odb_hot_water_volume"),
            "Hot water volume",
        )
        self.assertEqual(
            _sensor_name("en", "odb_heating_energy"),
            "Heating energy",
        )
        self.assertEqual(
            _sensor_name("en", "odb_possible_energy_saving"),
            "Possible energy saving",
        )
        self.assertEqual(
            _sensor_name("en", "odb_actual_water_saving"),
            "Actual water saving",
        )
        self.assertEqual(
            _sensor_name("de", "odb_hot_water_volume"),
            "Warmwasservolumen",
        )
        self.assertEqual(
            _sensor_name("de", "odb_heating_energy"),
            "Heizenergie",
        )
        self.assertEqual(
            _sensor_name("de", "odb_possible_energy_saving"),
            "Mögliche Energieeinsparung",
        )
        self.assertEqual(
            _sensor_name("de", "odb_actual_water_saving"),
            "Tatsächliche Wassereinsparung",
        )


if __name__ == "__main__":
    unittest.main()
