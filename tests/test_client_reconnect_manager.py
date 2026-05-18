"""Tests for the DHE reconnect grace and backoff manager."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MANAGER = (
    ROOT
    / "custom_components"
    / "stiebel_dhe_connect"
    / "client_reconnect_manager.py"
)


def _load_reconnect_manager():
    spec = importlib.util.spec_from_file_location("client_reconnect_manager", MANAGER)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestDHEReconnectManager(unittest.TestCase):
    """Validate reconnect grace, backoff and stable reset behavior."""

    def setUp(self) -> None:
        self.now = 0.0
        self.module = _load_reconnect_manager()

    def _manager(self):
        return self.module.DHEReconnectManager(
            base_delay=2.0,
            max_delay=10.0,
            stable_reset_after=60.0,
            grace_period=15.0,
            monotonic=lambda: self.now,
        )

    def test_first_disconnect_stays_available_inside_grace(self) -> None:
        manager = self._manager()

        manager.mark_connected()
        self.now = 1.0
        manager.mark_disconnected()

        self.assertEqual(manager.next_delay(), 2.0)
        self.assertTrue(manager.in_grace_period)
        self.assertFalse(manager.should_mark_unavailable)

    def test_grace_expires_from_first_disconnect(self) -> None:
        manager = self._manager()

        manager.mark_connected()
        self.now = 1.0
        manager.mark_disconnected()
        self.now = 10.0
        manager.mark_disconnected()
        self.now = 16.1

        self.assertEqual(manager.next_delay(), 4.0)
        self.assertFalse(manager.in_grace_period)
        self.assertTrue(manager.should_mark_unavailable)

    def test_backoff_caps_at_max_delay(self) -> None:
        manager = self._manager()

        for _ in range(8):
            manager.mark_disconnected()

        self.assertEqual(manager.next_delay(), 10.0)

    def test_stable_connection_resets_backoff_on_next_disconnect(self) -> None:
        manager = self._manager()

        manager.mark_disconnected()
        manager.mark_disconnected()
        self.assertEqual(manager.next_delay(), 4.0)

        self.now = 10.0
        manager.mark_connected()
        self.now = 71.0
        manager.mark_disconnected()

        self.assertEqual(manager.next_delay(), 2.0)


if __name__ == "__main__":
    unittest.main()
