"""Pure connection input helpers for config and options flows."""

from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import SplitResult, urlsplit


_HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)


def normalize_host(host: str) -> str:
    """Normalize and validate a host value from UI input."""
    value = host.strip()
    if not value:
        raise ValueError("empty_host")

    if "://" in value:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("invalid_scheme")
        if (
            parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("invalid_host")
        if _url_has_explicit_port(parsed):
            raise ValueError("embedded_port_not_supported")
        value = parsed.hostname or ""

    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1].strip()
    value = value.rstrip(".")

    if not value or any(char in value for char in "/?#@\\"):
        raise ValueError("invalid_host")

    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass

    # The port has a dedicated config field. Reject host:port to keep URL
    # construction deterministic and avoid ambiguity.
    if ":" in value:
        raise ValueError("embedded_port_not_supported")

    if not _HOST_RE.fullmatch(value):
        raise ValueError("invalid_host")

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


def validate_port(port: int) -> int:
    """Validate TCP port from UI input."""
    port = int(port)
    if port < 1 or port > 65535:
        raise ValueError("invalid_port")
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
        current_port = validate_port(int(current.get("port", default_port)))
    except (TypeError, ValueError):
        return True
    return (current_host, current_port) != (host, port)


def should_check_connectivity(*, target_changed: bool) -> bool:
    """Return whether options-flow connectivity checks should run."""
    return target_changed
