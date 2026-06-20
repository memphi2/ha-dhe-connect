"""Compatibility tests for translated action error helpers."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from custom_components.stiebel_dhe_connect import action_error_helpers  # noqa: E402


class _LegacyHomeAssistantError(Exception):
    """Legacy-like HomeAssistantError stub without translation kwargs support."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        if kwargs:
            raise TypeError("translation kwargs not supported")
        super().__init__(*args)


class TestActionErrorHelpersFallback(unittest.TestCase):
    """Validate fallback path when translation kwargs are unsupported."""

    def test_translated_error_falls_back_without_translation_kwargs(self) -> None:
        with patch.object(
            action_error_helpers,
            "HomeAssistantError",
            _LegacyHomeAssistantError,
        ):
            err = action_error_helpers._translated_homeassistant_error(
                "fallback-message",
                translation_key="dhe_action_failed",
                translation_placeholders={"operation": "test", "error": "boom"},
            )
        self.assertIsInstance(err, _LegacyHomeAssistantError)
        self.assertEqual(str(err), "fallback-message")


if __name__ == "__main__":
    unittest.main()
