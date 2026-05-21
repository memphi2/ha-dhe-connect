"""Tests for translated DHE action error helpers."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import unittest

from homeassistant.exceptions import HomeAssistantError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from custom_components.stiebel_dhe_connect.action_error_helpers import (  # noqa: E402
    dhe_action_error,
    raise_if_dhe_unavailable,
    run_dhe_action,
)
from custom_components.stiebel_dhe_connect.client_types import DHEError  # noqa: E402


class _Client:
    def __init__(self, available: bool) -> None:
        self.available = available


class TestActionErrorHelpers(unittest.TestCase):
    """Validate translated service/action exception behavior."""

    def test_dhe_action_error_uses_translation_key(self) -> None:
        error = dhe_action_error("Could not set DHE temperature", DHEError("boom"))
        self.assertIsInstance(error, HomeAssistantError)
        self.assertEqual(getattr(error, "translation_domain", None), "stiebel_dhe_connect")
        self.assertEqual(getattr(error, "translation_key", None), "dhe_action_failed")
        self.assertIn("boom", str(error))

    def test_raise_if_dhe_unavailable_uses_translation_key(self) -> None:
        with self.assertRaises(HomeAssistantError) as ctx:
            raise_if_dhe_unavailable(
                _Client(available=False),
                "DHE is unavailable; cannot select weather location",
            )
        err = ctx.exception
        self.assertEqual(getattr(err, "translation_domain", None), "stiebel_dhe_connect")
        self.assertEqual(getattr(err, "translation_key", None), "dhe_unavailable_action")

    def test_run_dhe_action_preserves_dhe_error_cause(self) -> None:
        async def _boom() -> None:
            raise DHEError("write rejected")

        with self.assertRaises(HomeAssistantError) as ctx:
            asyncio.run(run_dhe_action(_boom(), "Could not set DHE temperature"))
        self.assertIsInstance(ctx.exception.__cause__, DHEError)


if __name__ == "__main__":
    unittest.main()
