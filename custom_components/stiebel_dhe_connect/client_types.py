"""Shared DHE client models and type aliases."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Literal


DEFAULT_ENGINEIO_PING_INTERVAL_SECONDS = 25.0

ODBValue = bool | float
MeasurementValue = bool | float | str | None
ODBReadSource = Literal["requested", "runtime"]
ODB_READ_SOURCE_REQUESTED: Final[ODBReadSource] = "requested"
ODB_READ_SOURCE_RUNTIME: Final[ODBReadSource] = "runtime"
SetpointCallback = Callable[[float], None]
AvailabilityCallback = Callable[[bool], None]
OnlineCallback = Callable[[bool], None]
MeasurementCallback = Callable[[int, MeasurementValue], None]
ReconnectCallback = Callable[[int], None]
RadioCallback = Callable[[dict[str, Any]], None]
WeatherCallback = Callable[[dict[str, Any]], None]
DiagnosticCallback = Callable[[dict[str, Any]], None]
CallbackRemover = Callable[[], None]


class DHEError(Exception):
    """Base DHE exception."""


class DHESessionClosed(DHEError):
    """DHE closed the Socket.IO namespace/session."""


@dataclass
class DHEEvent:
    """Parsed Socket.IO event."""

    name: str
    data: Any


@dataclass
class DHESession:
    """Open Engine.IO/Socket.IO session context."""

    sid: str
    url_token: str
    websocket_sid: str | None = None
    ping_interval: float = DEFAULT_ENGINEIO_PING_INTERVAL_SECONDS
    websocket: Any | None = None
    websocket_ping_task: asyncio.Task[None] | None = None
