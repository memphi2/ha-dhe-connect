"""Pure Engine.IO frame parsing helpers."""

from __future__ import annotations

import json
from typing import Any


def decode_engineio_payload(text: str) -> list[str]:
    """Split an Engine.IO payload into packets."""
    if "\x1e" in text:
        return [part for part in text.split("\x1e") if part.strip()]
    if "\ufffd" in text:
        return [part for part in text.split("\ufffd") if part.strip()]
    packets: list[str] = []
    i = 0
    try:
        while i < len(text):
            if not text[i].isdigit():
                if packets:
                    i += 1
                    continue
                return [text]
            j = i
            while j < len(text) and text[j].isdigit():
                j += 1
            if j >= len(text) or text[j] != ":":
                return [text]
            length = int(text[i:j])
            start = j + 1
            end = start + length
            if end > len(text):
                return [text]
            packets.append(text[start:end])
            i = end
        return packets or [text]
    except ValueError:
        return [text]


def parse_engineio_open_payload(open_payload: str) -> dict[str, Any]:
    """Return the JSON body from an Engine.IO open packet."""
    for packet in decode_engineio_payload(open_payload):
        stripped = packet.strip("\x00\x1e\ufffd")
        if not stripped:
            continue
        if stripped.startswith("0"):
            stripped = stripped[1:].strip()
        if not stripped.startswith("{"):
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as err:
            raise ValueError(
                f"Could not parse DHE open payload: {open_payload!r}"
            ) from err
        if isinstance(parsed, dict):
            return parsed
    raise ValueError(f"Could not parse DHE open payload: {open_payload!r}")


def engineio_ping_interval(
    open_payload: dict[str, Any],
    *,
    default_interval: float,
) -> float:
    """Return an Engine.IO ping interval in seconds."""
    raw_interval = open_payload.get("pingInterval")
    if raw_interval is None:
        return default_interval
    try:
        return max(1.0, float(raw_interval) / 1000.0)
    except (TypeError, ValueError):
        return default_interval


def balanced_json_array(text: str, start_index: int) -> tuple[str | None, int]:
    """Return the first balanced JSON array at or after start_index."""
    start = text.find("[", start_index)
    if start < 0:
        return None, -1
    depth = 0
    idx = start
    while idx < len(text):
        ch = text[idx]
        if ch == '"':
            idx = _json_string_end(text, idx + 1)
            if idx < 0:
                return None, -1
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1], idx + 1
        idx += 1
    return None, -1


def _json_string_end(text: str, idx: int) -> int:
    """Return the index after a JSON string, preserving malformed content."""
    escape = False
    while idx < len(text):
        ch = text[idx]
        if escape:
            escape = False
        elif ch == "\\":
            escape = True
        elif ch == '"':
            return idx + 1
        idx += 1
    return -1
