"""Connection supervision policy for the DHE client."""

from __future__ import annotations

import time
from collections.abc import Callable


class DHEConnectionSupervisor:
    """Track reconnect state without driving Home Assistant entity polling."""

    def __init__(
        self,
        *,
        base_delay: float = 2.0,
        max_delay: float = 180.0,
        stable_reset_after: float = 60.0,
        grace_period: float = 15.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._base_delay = max(0.0, float(base_delay))
        self._max_delay = max(self._base_delay, float(max_delay))
        self._stable_reset_after = max(0.0, float(stable_reset_after))
        self._grace_period = max(0.0, float(grace_period))
        self._monotonic = monotonic
        self._attempts = 0
        self._connected_at: float | None = None
        self._disconnected_at: float | None = None
        self._next_delay = 0.0
        self._successful_reconnect_count = 0
        self._last_successful_reconnect_duration: float | None = None
        self._total_successful_reconnect_duration = 0.0

    def next_delay(self) -> float:
        """Return the delay before the next reconnect attempt."""
        return self._next_delay

    def grace_seconds_remaining(self) -> float | None:
        """Return seconds until reconnect grace expires, or None when connected."""
        if self._disconnected_at is None:
            return None
        elapsed = self._monotonic() - self._disconnected_at
        return max(0.0, self._grace_period - elapsed)

    def mark_connected(self, *, count_reconnect: bool = True) -> None:
        """Record a healthy connection."""
        now = self._monotonic()
        if count_reconnect and self._disconnected_at is not None:
            duration = round(max(0.0, now - self._disconnected_at), 3)
            self._successful_reconnect_count += 1
            self._last_successful_reconnect_duration = duration
            self._total_successful_reconnect_duration += duration
        self._connected_at = now
        self._disconnected_at = None
        self._next_delay = 0.0

    def mark_disconnected(self) -> None:
        """Record a reconnectable disconnect and update the backoff delay."""
        now = self._monotonic()
        if self._connected_at is not None:
            if now - self._connected_at >= self._stable_reset_after:
                self._attempts = 0
            self._connected_at = None
        if self._disconnected_at is None:
            self._disconnected_at = now
        self._attempts += 1
        exponent = min(max(0, self._attempts - 1), 60)
        self._next_delay = min(
            self._max_delay,
            self._base_delay * (2**exponent),
        )

    @property
    def in_grace_period(self) -> bool:
        """Return true while entities should stay available during reconnect."""
        if self._disconnected_at is None:
            return False
        return self._monotonic() - self._disconnected_at < self._grace_period

    @property
    def should_mark_unavailable(self) -> bool:
        """Return true when the reconnect grace window has expired."""
        return self._disconnected_at is not None and not self.in_grace_period

    def diagnostic_state(self) -> dict[str, float | int | bool | None]:
        """Return anonymized reconnect policy state for support diagnostics."""
        average_reconnect_interval = (
            round(
                self._total_successful_reconnect_duration
                / self._successful_reconnect_count,
                3,
            )
            if self._successful_reconnect_count
            else None
        )
        return {
            "attempts": self._attempts,
            "successful_reconnect_count": self._successful_reconnect_count,
            "average_reconnect_interval_seconds": average_reconnect_interval,
            "last_successful_reconnect_duration_seconds": (
                self._last_successful_reconnect_duration
            ),
            "next_delay_seconds": self._next_delay,
            "in_grace_period": self.in_grace_period,
            "should_mark_unavailable": self.should_mark_unavailable,
            "grace_seconds_remaining": self.grace_seconds_remaining(),
            "base_delay_seconds": self._base_delay,
            "max_delay_seconds": self._max_delay,
            "stable_reset_after_seconds": self._stable_reset_after,
            "grace_period_seconds": self._grace_period,
        }
