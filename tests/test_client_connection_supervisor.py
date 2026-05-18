"""Tests for the DHE connection supervisor."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR = (
    ROOT
    / "custom_components"
    / "stiebel_dhe_connect"
    / "client_connection_supervisor.py"
)


def _load_connection_supervisor():
    spec = importlib.util.spec_from_file_location(
        "client_connection_supervisor",
        SUPERVISOR,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestDHEConnectionSupervisor(unittest.TestCase):
    """Validate reconnect grace, backoff and stable reset behavior."""

    def setUp(self) -> None:
        self.now = 0.0
        self.module = _load_connection_supervisor()

    def _supervisor(self):
        return self.module.DHEConnectionSupervisor(
            base_delay=2.0,
            max_delay=10.0,
            stable_reset_after=60.0,
            grace_period=15.0,
            monotonic=lambda: self.now,
        )

    def test_first_disconnect_stays_available_inside_grace(self) -> None:
        supervisor = self._supervisor()

        supervisor.mark_connected()
        self.now = 1.0
        supervisor.mark_disconnected()

        self.assertEqual(supervisor.next_delay(), 2.0)
        self.assertTrue(supervisor.in_grace_period)
        self.assertFalse(supervisor.should_mark_unavailable)
        self.assertEqual(supervisor.grace_seconds_remaining(), 15.0)

    def test_grace_expires_from_first_disconnect(self) -> None:
        supervisor = self._supervisor()

        supervisor.mark_connected()
        self.now = 1.0
        supervisor.mark_disconnected()
        self.now = 10.0
        supervisor.mark_disconnected()
        self.now = 16.1

        self.assertEqual(supervisor.next_delay(), 4.0)
        self.assertFalse(supervisor.in_grace_period)
        self.assertTrue(supervisor.should_mark_unavailable)
        self.assertEqual(supervisor.grace_seconds_remaining(), 0.0)

    def test_backoff_caps_at_max_delay(self) -> None:
        supervisor = self._supervisor()

        for _ in range(8):
            supervisor.mark_disconnected()

        self.assertEqual(supervisor.next_delay(), 10.0)

    def test_stable_connection_resets_backoff_on_next_disconnect(self) -> None:
        supervisor = self._supervisor()

        supervisor.mark_disconnected()
        supervisor.mark_disconnected()
        self.assertEqual(supervisor.next_delay(), 4.0)

        self.now = 10.0
        supervisor.mark_connected()
        self.now = 71.0
        supervisor.mark_disconnected()

        self.assertEqual(supervisor.next_delay(), 2.0)
        self.assertEqual(supervisor.grace_seconds_remaining(), 15.0)

        supervisor.mark_connected()

        self.assertIsNone(supervisor.grace_seconds_remaining())


if __name__ == "__main__":
    unittest.main()
