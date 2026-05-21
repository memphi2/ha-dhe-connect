"""Helpers for deterministic and bounded token file paths."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterable

TOKEN_FILE_HOST_COMPONENT_MAX = 120
LEGACY_TOKEN_FILE = ".storage/stiebel_dhe_connect_token.txt"
TOKEN_FILE_PREFIX = "stiebel_dhe_connect_token_"
TOKEN_FILE_SUFFIX = ".txt"
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


def legacy_token_file_for_entry(entry_id: str) -> str:
    """Return the old entry-id based token path used by early multi-device builds."""
    return f".storage/stiebel_dhe_connect_token_{entry_id}.txt"


def legacy_token_files_for_target(host: str, port: int) -> tuple[str, ...]:
    """Return older host-derived token paths for one DHE target."""
    safe_host = _normalize_token_file_component(host)
    legacy_path = f".storage/stiebel_dhe_connect_token_{safe_host}_{port}.txt"
    current_path = token_file_for_target(host, port)
    if legacy_path == current_path:
        return ()
    return (legacy_path,)


def stale_unconfigured_token_paths(
    storage_path: str,
    file_names: Iterable[str],
    configured_paths: Iterable[str],
) -> set[str]:
    """Return token files in storage_path that are not owned by a config entry."""
    normalized_configured_paths = {
        os.path.normcase(os.path.abspath(path)) for path in configured_paths
    }
    paths: set[str] = set()
    for file_name in file_names:
        if not (
            file_name.startswith(TOKEN_FILE_PREFIX)
            and file_name.endswith(TOKEN_FILE_SUFFIX)
        ):
            continue
        path = os.path.normcase(os.path.abspath(os.path.join(storage_path, file_name)))
        if path not in normalized_configured_paths:
            paths.add(path)
    return paths
