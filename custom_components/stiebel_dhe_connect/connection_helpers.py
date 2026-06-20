"""Pure connection input helpers for config and options flows."""

from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import SplitResult, urlsplit

try:
    from .error_codes import (
        EMPTY_HOST,
        EMBEDDED_PORT_NOT_SUPPORTED,
        INVALID_HOST,
        INVALID_PORT,
        INVALID_SCHEME,
    )
except ImportError:  # pragma: no cover - compatibility for direct module loading in tests
    from custom_components.stiebel_dhe_connect.error_codes import (
        EMPTY_HOST,
        EMBEDDED_PORT_NOT_SUPPORTED,
        INVALID_HOST,
        INVALID_PORT,
        INVALID_SCHEME,
    )


_HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)


def normalize_host(host: str) -> str:
    """Normalize and validate a host value from UI input."""
    value = host.strip()
    if not value:
        raise ValueError(EMPTY_HOST)

    if "://" in value:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError(INVALID_SCHEME)
        if (
            parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(INVALID_HOST)
        if _url_has_explicit_port(parsed):
            raise ValueError(EMBEDDED_PORT_NOT_SUPPORTED)
        value = parsed.hostname or ""

    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1].strip()
    value = value.rstrip(".")

    if not value or any(char in value for char in "/?#@\\"):
        raise ValueError(INVALID_HOST)

    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass

    # The port has a dedicated config field. Reject host:port to keep URL
    # construction deterministic and avoid ambiguity.
    if ":" in value:
        raise ValueError(EMBEDDED_PORT_NOT_SUPPORTED)

    if not _HOST_RE.fullmatch(value):
        raise ValueError(INVALID_HOST)

    return value.lower()


def _url_has_explicit_port(parsed: SplitResult) -> bool:
    """Return whether a parsed URL explicitly contains a port."""
    try:
        return parsed.port is not None
    except ValueError:
        return True


def host_for_url(host: str) -> str:
    """Return host part suitable for URL construction."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host
    if ip.version == 6:
        return f"[{host}]"
    return host


def validate_port(port: int | str) -> int:
    """Validate TCP port from UI input."""
    if isinstance(port, bool):
        raise ValueError(INVALID_PORT)
    if isinstance(port, float):
        raise ValueError(INVALID_PORT)
    port = int(port)
    if port < 1 or port > 65535:
        raise ValueError(INVALID_PORT)
    return port


def target_changed(
    current: dict[str, Any],
    host: str,
    port: int,
    *,
    default_port: int,
) -> bool:
    """Return whether a submitted host/port differs from current entry data."""
    try:
        current_host = normalize_host(str(current.get("host", "")))
        current_port = validate_port(current.get("port", default_port))
    except (TypeError, ValueError):
        return True
    return (current_host, current_port) != (host, port)
