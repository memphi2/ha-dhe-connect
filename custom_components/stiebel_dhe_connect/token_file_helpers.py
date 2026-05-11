"""Helpers for deterministic and bounded token file paths."""

from __future__ import annotations

import hashlib
import re

TOKEN_FILE_HOST_COMPONENT_MAX = 120
_TOKEN_FILE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9_.-]")


def _normalize_token_file_component(value: str) -> str:
    safe = _TOKEN_FILE_COMPONENT_RE.sub("_", value.strip())
    return safe or "device"


def _bounded_host_component(host: str) -> str:
    """Return a filesystem-safe host component with bounded length."""
    safe_host = _normalize_token_file_component(host)
    if len(safe_host) <= TOKEN_FILE_HOST_COMPONENT_MAX:
        return safe_host

    digest = hashlib.sha256(safe_host.encode("utf-8")).hexdigest()[:16]
    prefix_len = TOKEN_FILE_HOST_COMPONENT_MAX - len(digest) - 1
    return f"{safe_host[:prefix_len]}_{digest}"


def token_file_for_target(host: str, port: int) -> str:
    """Return per-target token path under Home Assistant .storage."""
    safe_host = _bounded_host_component(host)
    return f".storage/stiebel_dhe_connect_token_{safe_host}_{port}.txt"

