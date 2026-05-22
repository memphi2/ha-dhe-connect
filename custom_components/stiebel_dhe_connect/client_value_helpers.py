"""Pure value conversion helpers for the DHE client."""

from __future__ import annotations

from typing import Any

from .client_types import (
    ODB_READ_SOURCE_REQUESTED,
    ODBReadSource,
    ODBValue,
)
from .protocol import (
    ODB_ZERO_REQUEST_READBACK_IGNORE_IDS,
    TEMPERATURE_MEMORY_BUTTON_ADDR,
    WATER_HEATING_OFF_RAW,
    WATER_HEATING_ON_RAW,
)


def round_to_half_c(value: float) -> float:
    """Round a Celsius value to the nearest half degree."""
    return round(value * 2.0) / 2.0


def clamp(value: float, lo: float, hi: float) -> float:
    """Clamp a numeric value to an inclusive range."""
    return max(lo, min(hi, value))


def c_to_raw_tenths(value: float) -> int:
    """Encode Celsius as a raw tenths integer."""
    return round(value * 10.0)


def raw_tenths_to_c(value: int | float) -> float:
    """Decode a raw tenths value as Celsius."""
    return float(value) / 10.0


def raw_to_float(value: Any) -> float:
    """Decode numeric values published by the DHE protocol."""
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
    return float(value)


def build_req66(temp_c: float, addr: int) -> int:
    """Build the packed request value used by temperature memory buttons."""
    raw = c_to_raw_tenths(temp_c) & 1023
    return int(raw | ((addr & 0xFF) << 10))


def build_temperature_memory_button_value(temp_c: float) -> int:
    """Build the packed request value for the configured memory button address."""
    return build_req66(temp_c, TEMPERATURE_MEMORY_BUTTON_ADDR)


def raw_to_bool(value: Any) -> bool:
    """Decode a DHE boolean-ish value."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "on", "yes"}:
            return True
        if lowered in {"false", "off", "no", ""}:
            return False
    return bool(int(raw_to_float(value)))


def raw_to_water_heating_enabled(value: Any) -> bool:
    """Decode ODB id 33 value to water-heating enabled state."""
    return int(raw_to_float(value)) == WATER_HEATING_ON_RAW


def should_publish_odb_readback(
    odb_id: int,
    raw_value: Any,
    *,
    source: ODBReadSource,
) -> bool:
    """Return whether an ODB readback should update Home Assistant state."""
    if source != ODB_READ_SOURCE_REQUESTED:
        return True
    if odb_id not in ODB_ZERO_REQUEST_READBACK_IGNORE_IDS:
        return True
    return raw_to_float(raw_value) != 0.0


def water_heating_enabled_to_raw(enabled: bool) -> int:
    """Encode water-heating enabled state to ODB id 33 value."""
    return WATER_HEATING_ON_RAW if enabled else WATER_HEATING_OFF_RAW


def values_equal(a: ODBValue | None, b: ODBValue | None) -> bool:
    """Compare confirmed ODB values with the tolerance used by the DHE."""
    if a is None or b is None:
        return a is b
    if a == b:
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) is bool(b)
    return abs(float(a) - float(b)) < 0.001
