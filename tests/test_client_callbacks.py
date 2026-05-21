"""Tests for DHE client callback registration helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from custom_components.stiebel_dhe_connect.client_callbacks import (
    DHEClientCallbacksMixin,
)
from custom_components.stiebel_dhe_connect.client_types import MeasurementValue


class _CallbackClient(DHEClientCallbacksMixin):
    """Minimal callback client for pure callback tests."""

    def __init__(self) -> None:
        self._measurement_callbacks: set[Callable[..., None]] = set()
        self._last_measurements: dict[int, MeasurementValue] = {1: 10, 2: 20}
        self._temperature_memory_full_list_seen = False


def test_measurement_callback_replays_startup_values_by_default() -> None:
    """Keep the legacy replay behavior for callers that need it."""
    client = _CallbackClient()
    calls: list[tuple[Any, ...]] = []

    client.add_measurement_callback(lambda *args: calls.append(args))

    assert calls == [(1, 10), (2, 20)]


def test_measurement_callback_can_skip_startup_replay() -> None:
    """Allow entity setup to avoid N entities times M startup replay fanout."""
    client = _CallbackClient()
    calls: list[tuple[Any, ...]] = []

    remove = client.add_measurement_callback(
        lambda *args: calls.append(args),
        replay=False,
    )
    assert calls == []

    client._notify_callbacks("measurement", client._measurement_callbacks, 1, 30)
    assert calls == [(1, 30)]

    remove()
    client._notify_callbacks("measurement", client._measurement_callbacks, 1, 40)
    assert calls == [(1, 30)]
