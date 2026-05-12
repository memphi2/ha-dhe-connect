"""Pure helpers for entity state conversion and availability."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

CONF_INTERNAL_SCALD_PROTECTION = "internal_scald_protection"
INTERNAL_SCALD_PROTECTION_DEFAULT = "60"
INTERNAL_SCALD_PROTECTION_OPTIONS = ("43", "50", "55", "60", "no_jumper")
INTERNAL_SCALD_PROTECTION_LIMITS = {
    "43": 43.0,
    "50": 50.0,
    "55": 55.0,
    "60": 60.0,
    "no_jumper": 43.0,
}


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


def normalize_internal_scald_protection(value: Any) -> str:
    """Return a supported internal scald-protection jumper option."""
    option = str(value or "").strip()
    if option in INTERNAL_SCALD_PROTECTION_OPTIONS:
        return option
    return INTERNAL_SCALD_PROTECTION_DEFAULT


def internal_scald_protection_temperature(value: Any) -> float:
    """Return the effective temperature limit for the configured jumper option."""
    option = normalize_internal_scald_protection(value)
    return INTERNAL_SCALD_PROTECTION_LIMITS[option]


def child_safety_temperature_limit_max(
    internal_scald_protection: Any,
    *,
    maximum: float = 60.0,
) -> float:
    """Return the maximum child-safety limit allowed by the jumper."""
    return min(maximum, internal_scald_protection_temperature(internal_scald_protection))


def bounded_child_safety_temperature_limit(
    value: Any,
    *,
    internal_scald_protection: Any,
    minimum: float = 20.0,
    maximum: float = 60.0,
) -> float | None:
    """Return a child-safety limit bounded by the physical jumper position."""
    temperature = coerce_float(value)
    if temperature is None:
        return None
    return max(
        minimum,
        min(
            child_safety_temperature_limit_max(
                internal_scald_protection,
                maximum=maximum,
            ),
            temperature,
        ),
    )


def climate_max_temperature(
    *,
    internal_scald_protection: Any,
    child_safety_active: bool | None,
    child_safety_temperature_limit: Any,
    minimum: float = 20.0,
    maximum: float = 60.0,
) -> float:
    """Return the Climate max temperature from Tmax and child-safety limits."""
    max_temp = child_safety_temperature_limit_max(
        internal_scald_protection,
        maximum=maximum,
    )
    child_limit = coerce_float(child_safety_temperature_limit)
    if child_safety_active and child_limit is not None:
        max_temp = min(max_temp, child_limit)
    return max(minimum, min(maximum, max_temp))


def clamp_temperature(
    value: Any,
    *,
    minimum: float,
    maximum: float,
) -> float | None:
    """Return a temperature clamped to the supplied range."""
    temperature = coerce_float(value)
    if temperature is None:
        return None
    return max(minimum, min(maximum, temperature))


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
