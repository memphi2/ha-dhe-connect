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

    def test_successful_reconnect_metrics_track_disconnect_duration(self) -> None:
        supervisor = self._supervisor()

        supervisor.mark_connected()
        self.now = 10.0
        supervisor.mark_disconnected()
        self.now = 14.5
        supervisor.mark_connected()
        self.now = 30.0
        supervisor.mark_disconnected()
        self.now = 35.5
        supervisor.mark_connected()

        diagnostics = supervisor.diagnostic_state()
        self.assertEqual(diagnostics["successful_reconnect_count"], 2)
        self.assertEqual(diagnostics["last_successful_reconnect_duration_seconds"], 5.5)
        self.assertEqual(diagnostics["average_reconnect_interval_seconds"], 5.0)

    def test_initial_connect_can_skip_successful_reconnect_metric(self) -> None:
        supervisor = self._supervisor()

        supervisor.mark_disconnected()
        self.now = 2.0
        supervisor.mark_connected(count_reconnect=False)

        diagnostics = supervisor.diagnostic_state()
        self.assertEqual(diagnostics["successful_reconnect_count"], 0)
        self.assertIsNone(diagnostics["last_successful_reconnect_duration_seconds"])
        self.assertIsNone(diagnostics["average_reconnect_interval_seconds"])

    def test_diagnostic_state_summarizes_policy_without_targets(self) -> None:
        supervisor = self._supervisor()

        supervisor.mark_connected()
        self.now = 1.0
        supervisor.mark_disconnected()
        self.now = 3.5

        self.assertEqual(
            supervisor.diagnostic_state(),
            {
                "attempts": 1,
                "successful_reconnect_count": 0,
                "average_reconnect_interval_seconds": None,
                "last_successful_reconnect_duration_seconds": None,
                "next_delay_seconds": 2.0,
                "in_grace_period": True,
                "should_mark_unavailable": False,
                "grace_seconds_remaining": 12.5,
                "base_delay_seconds": 2.0,
                "max_delay_seconds": 10.0,
                "stable_reset_after_seconds": 60.0,
                "grace_period_seconds": 15.0,
            },
        )


if __name__ == "__main__":
    unittest.main()
