"""Pure helpers for entity state conversion and availability."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def coerce_float(value: Any) -> float | None:
    """Return value as float, ignoring bools and invalid values."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_minutes_duration(value: Any) -> str | None:
    """Format a minute value as m:ss for Home Assistant display."""
    minutes_value = coerce_float(value)
    if minutes_value is None:
        return None
    total_seconds = max(0, int(round(minutes_value * 60)))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def minutes_to_seconds(value: Any) -> float | None:
    """Convert a numeric minute value to seconds."""
    minutes_value = coerce_float(value)
    if minutes_value is None:
        return None
    return float(round(minutes_value * 60.0, 3))


def seconds_to_minutes(value: Any) -> float | None:
    """Convert a numeric second value to minutes."""
    seconds_value = coerce_float(value)
    if seconds_value is None:
        return None
    return seconds_value / 60.0


def clamp_duration_seconds(
    value: Any,
    *,
    minimum: int,
    maximum: int,
) -> int | None:
    """Return a whole-second duration clamped to the supported range."""
    seconds_value = coerce_float(value)
    if seconds_value is None:
        return None
    return max(minimum, min(int(round(seconds_value)), maximum))


def duration_minutes_part(value: Any) -> int | None:
    """Return the minute component from a whole-second duration."""
    seconds_value = coerce_float(value)
    if seconds_value is None:
        return None
    return max(0, int(round(seconds_value)) // 60)


def duration_seconds_part(value: Any) -> int | None:
    """Return the second component from a whole-second duration."""
    seconds_value = coerce_float(value)
    if seconds_value is None:
        return None
    return max(0, int(round(seconds_value)) % 60)


def replace_duration_part(
    current_total_seconds: Any,
    part: str,
    value: Any,
    *,
    minimum: int,
    maximum: int,
) -> int | None:
    """Return a duration with one minute/second component replaced."""
    requested = coerce_float(value)
    current = clamp_duration_seconds(
        current_total_seconds,
        minimum=minimum,
        maximum=maximum,
    )
    if requested is None or current is None:
        return None

    minutes, seconds = divmod(current, 60)
    if part == "minutes":
        minutes = max(0, int(round(requested)))
    elif part == "seconds":
        seconds = max(0, min(int(round(requested)), 59))
    else:
        return None

    return clamp_duration_seconds(
        minutes * 60 + seconds,
        minimum=minimum,
        maximum=maximum,
    )


def value_available(connected: bool, value: Any) -> bool:
    """Return whether an entity is connected and has a known value."""
    return bool(connected) and value is not None


def connected_or_known_available(connected: bool, *values: Any) -> bool:
    """Return whether an entity is connected or has any cached known value."""
    return bool(connected) or any(value is not None for value in values)


def connected_and_ready(connected: bool, ready: bool) -> bool:
    """Return whether an entity is connected and its backing state is ready."""
    return bool(connected) and bool(ready)


def measurement_attribute_text(
    attributes: Mapping[str, Any] | None,
    key: str,
) -> str | None:
    """Return one non-empty measurement attribute as text."""
    if not isinstance(attributes, Mapping):
        return None
    value = attributes.get(key)
    if value in (None, ""):
        return None
    return str(value)


def merge_state_attributes(
    base: Mapping[str, Any],
    dynamic: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Merge static and dynamic state attributes without mutating inputs."""
    attributes = dict(base)
    if isinstance(dynamic, Mapping):
        attributes.update(dynamic)
    return attributes
