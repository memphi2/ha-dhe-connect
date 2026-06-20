"""Tests for the translation key guard script."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import check_translation_keys


def _write_locale(root: Path, locale: str, body: dict[str, object]) -> None:
    path = root / f"{locale}.json"
    path.write_text(json.dumps(body), encoding="utf-8")


def _translation_fixture() -> dict[str, object]:
    return {
        "config": {
            "error": {
                "cannot_connect": "",
                "pairing_required": "",
                "token_invalid": "",
                "invalid_internal_scald_protection": "",
                "invalid_port": "",
                "invalid_setup_mode": "",
            },
            "abort": {
                "already_configured": "",
                "invalid_discovery_parameters": "",
                "conflicting_discovery_identity": "",
                "low_confidence_discovery": "",
            },
        },
        "options": {
            "error": {
                "cannot_connect": "",
                "device_settings_failed": "",
                "not_loaded": "",
            }
        },
        "issues": {
            "pairing_required": {
                "fix_flow": {"abort": {"entry_not_found": "", "invalid_entry": ""}}
            },
            "token_invalid": {
                "fix_flow": {"abort": {"entry_not_found": "", "invalid_entry": ""}}
            },
            "device_unreachable": {},
            "discovery_conflict": {},
            "host_changed_or_unreachable": {},
        },
        "exceptions": {
            "dhe_action_failed": "",
            "dhe_unavailable_action": "",
            "dhe_not_loaded": "",
            "dhe_entry_not_loaded": "",
            "dhe_entry_id_required": "",
            "dhe_invalid_config_entry": "",
            "dhe_weather_country_required": "",
            "dhe_weather_location_not_found": "",
            "dhe_weather_result_unavailable": "",
            "dhe_weather_location_id_empty": "",
            "dhe_unknown_weather_location_option": "",
            "dhe_unknown_radio_source": "",
            "dhe_no_radio_favorites": "",
            "dhe_unsupported_hvac_mode": "",
        },
    }


class TestCheckTranslationKeys(unittest.TestCase):
    """Validate required translation key checks."""

    def test_accepts_minimal_valid_translation_files(self) -> None:
        base = _translation_fixture()
        with tempfile.TemporaryDirectory() as temp_dir:
            translations = Path(temp_dir)
            _write_locale(translations, "en", base)
            _write_locale(translations, "de", base)

            with patch.object(check_translation_keys, "TRANSLATIONS", translations):
                self.assertEqual(check_translation_keys.main(), 0)

    def test_rejects_missing_required_key(self) -> None:
        valid = _translation_fixture()
        missing = json.loads(json.dumps(valid))
        missing["config"]["error"].pop("invalid_setup_mode", None)
        with tempfile.TemporaryDirectory() as temp_dir:
            translations = Path(temp_dir)
            _write_locale(translations, "en", missing)
            _write_locale(translations, "de", valid)

            with patch.object(check_translation_keys, "TRANSLATIONS", translations):
                self.assertEqual(check_translation_keys.main(), 1)


if __name__ == "__main__":
    unittest.main()
