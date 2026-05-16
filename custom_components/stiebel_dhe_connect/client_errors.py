"""Client exception classification helpers."""

from __future__ import annotations

import aiohttp

from .client_types import DHEError


DHE_COMMAND_EXCEPTIONS = (
    DHEError,
    aiohttp.ClientError,
    TimeoutError,
    OSError,
    ValueError,
)
DHE_TRANSPORT_EXCEPTIONS = (*DHE_COMMAND_EXCEPTIONS, RuntimeError)
RUNTIME_TRANSPORT_ERROR_MARKERS = (
    "cannot write to closing transport",
    "connection closed",
    "connector is closed",
    "session is closed",
    "socket",
    "transport",
    "websocket",
)


def is_runtime_transport_error(err: RuntimeError) -> bool:
    """Return true for RuntimeError messages produced by transport shutdown races."""
    message = str(err).lower()
    return any(marker in message for marker in RUNTIME_TRANSPORT_ERROR_MARKERS)
