"""Client exception classification helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import re

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
RUNTIME_TRANSPORT_ERROR_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bcannot write to closing transport\b",
        r"\bclosing transport\b",
        r"\bconnection reset by peer\b",
        r"\b(?:connection|connector|session)\s+(?:is\s+)?closed\b",
        r"\bsocket\s+(?:is\s+)?(?:closed|closing|disconnected|reset|shutdown)\b",
        r"\b(?:socket|web ?socket|transport)\s+write\s+failed\b",
        r"\btransport\s+(?:is\s+)?(?:closed|closing|lost|shutdown)\b",
        r"\bweb ?socket(?:\s+connection)?\s+(?:is\s+)?(?:closed|closing|disconnected|shutdown)\b",
    )
)


def is_runtime_transport_error(err: RuntimeError) -> bool:
    """Return true for RuntimeError messages produced by transport shutdown races."""
    message = str(err).lower()
    return any(pattern.search(message) for pattern in RUNTIME_TRANSPORT_ERROR_PATTERNS)


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
