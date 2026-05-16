"""Client exception classification helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import aiohttp

from .client_types import DHEError


DHE_COMMAND_EXCEPTIONS = (
    DHEError,
    aiohttp.ClientError,
    TimeoutError,
    OSError,
    ValueError,
)
DHE_TRANSPORT_EXCEPTIONS = DHE_COMMAND_EXCEPTIONS
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


def runtime_transport_error_or_raise(err: RuntimeError) -> RuntimeError:
    """Return runtime transport errors and re-raise programming RuntimeErrors."""
    if is_runtime_transport_error(err):
        return err
    raise err


@contextmanager
def suppress_transport_errors() -> Iterator[None]:
    """Suppress transport errors while preserving unrelated RuntimeErrors."""
    try:
        yield
    except DHE_TRANSPORT_EXCEPTIONS:
        return
    except RuntimeError as err:
        runtime_transport_error_or_raise(err)
