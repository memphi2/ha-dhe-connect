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

    def test_required_flow_and_issue_keys_exist_in_en_and_de(self) -> None:
        required_config_errors = {
            "cannot_connect",
            "invalid_internal_scald_protection",
            "invalid_port",
            "invalid_setup_mode",
        }
        required_config_aborts = {
            "already_configured",
            "conflicting_discovery_identity",
            "invalid_discovery_parameters",
            "low_confidence_discovery",
        }
        required_options_errors = {
            "device_settings_failed",
            "not_loaded",
        }
        required_issue_fix_flow_aborts = {
            "entry_not_found",
            "invalid_entry",
        }

        for locale in ("en", "de"):
            data = json.loads((TRANSLATIONS / f"{locale}.json").read_text(encoding="utf-8"))
            self.assertTrue(required_config_errors <= set(data["config"]["error"]))
            self.assertTrue(required_config_aborts <= set(data["config"]["abort"]))
            self.assertTrue(required_options_errors <= set(data["options"]["error"]))

            issue_pairing = data["issues"]["pairing_required"]["fix_flow"]["abort"]
            issue_token = data["issues"]["token_invalid"]["fix_flow"]["abort"]
            self.assertTrue(required_issue_fix_flow_aborts <= set(issue_pairing))
            self.assertTrue(required_issue_fix_flow_aborts <= set(issue_token))

    def test_action_exception_translation_keys_exist_in_en_and_de(self) -> None:
        for locale in ("en", "de"):
            data = json.loads((TRANSLATIONS / f"{locale}.json").read_text(encoding="utf-8"))
            exceptions = data["exceptions"]
            self.assertTrue(
                {
                    "dhe_action_failed",
                    "dhe_unavailable_action",
                    "dhe_not_loaded",
                    "dhe_entry_not_loaded",
                    "dhe_entry_id_required",
                    "dhe_invalid_config_entry",
                    "dhe_weather_country_required",
                    "dhe_weather_location_not_found",
                    "dhe_weather_result_unavailable",
                    "dhe_weather_location_id_empty",
                    "dhe_unknown_weather_location_option",
                    "dhe_unknown_radio_source",
                    "dhe_no_radio_favorites",
                    "dhe_unsupported_hvac_mode",
                }
                <= set(exceptions)
            )


if __name__ == "__main__":
    unittest.main()
