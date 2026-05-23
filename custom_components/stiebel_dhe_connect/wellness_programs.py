"""Wellness program catalog helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .client_value_helpers import raw_to_bool as _raw_to_bool
from .client_value_helpers import raw_to_float as _raw_to_float

WELLNESS_PROGRAM_KEYS_BY_ID = {
    1: "wellness_cold_prevention",
    2: "wellness_winter_pick_me_up",
    3: "wellness_summer_fitness",
    4: "wellness_circulation_boost",
}

_FALLBACK_WELLNESS_PROGRAMS: tuple[dict[str, Any], ...] = (
    {
        "id": 1,
        "key": "wellness_cold_prevention",
        "name": "Cold prevention",
        "coldwater": True,
    },
    {
        "id": 2,
        "key": "wellness_winter_pick_me_up",
        "name": "Winter pick-me-up",
        "coldwater": False,
    },
    {
        "id": 3,
        "key": "wellness_summer_fitness",
        "name": "Summer fitness",
        "coldwater": True,
    },
    {
        "id": 4,
        "key": "wellness_circulation_boost",
        "name": "Circulation boost",
        "coldwater": True,
    },
)


def fallback_wellness_programs() -> tuple[dict[str, Any], ...]:
    """Return the known DHE wellness programs used before live catalog data."""
    return _copy_programs(_FALLBACK_WELLNESS_PROGRAMS)


def normalize_wellness_programs(raw_value: Any) -> tuple[dict[str, Any], ...]:
    """Return normalized wellness program metadata from a DHE app payload."""
    if not isinstance(raw_value, list):
        return ()

    programs: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for item in raw_value:
        program = _normalize_wellness_program(item)
        if program is None:
            continue
        program_id = int(program["id"])
        if program_id in seen_ids:
            continue
        seen_ids.add(program_id)
        programs.append(program)
    return tuple(sorted(programs, key=lambda program: int(program["id"])))


def wellness_program_by_id(
    programs: tuple[dict[str, Any], ...],
    program_id: int,
) -> dict[str, Any]:
    """Return one program by id, falling back to the known DHE catalog."""
    for program in programs:
        if program.get("id") == program_id:
            return dict(program)
    for program in _FALLBACK_WELLNESS_PROGRAMS:
        if program.get("id") == program_id:
            return dict(program)
    return {
        "id": program_id,
        "key": f"wellness_program_{program_id}",
        "name": f"Wellness program {program_id}",
    }


def _normalize_wellness_program(raw_value: Any) -> dict[str, Any] | None:
    if not isinstance(raw_value, Mapping):
        return None
    try:
        program_id = int(raw_value["id"])
    except (KeyError, TypeError, ValueError):
        return None
    if program_id <= 0:
        return None

    fallback = wellness_program_by_id((), program_id)
    # Keep canonical program names for known program IDs so HA names and
    # attributes stay stable across DHE locale changes.
    fallback_name = str(fallback["name"])
    live_name = _clean_text(raw_value.get("name"))
    name = (
        fallback_name
        if program_id in WELLNESS_PROGRAM_KEYS_BY_ID
        else (live_name or fallback_name)
    )
    program: dict[str, Any] = {
        "id": program_id,
        "key": WELLNESS_PROGRAM_KEYS_BY_ID.get(
            program_id,
            f"wellness_program_{program_id}",
        ),
        "name": name,
    }

    if "coldwater" in raw_value:
        try:
            program["coldwater"] = _raw_to_bool(raw_value["coldwater"])
        except (TypeError, ValueError):
            if "coldwater" in fallback:
                program["coldwater"] = bool(fallback["coldwater"])
    elif "coldwater" in fallback:
        program["coldwater"] = bool(fallback["coldwater"])

    for source_key, target_key in (
        ("hot", "hot_temperature"),
        ("hot_temperature", "hot_temperature"),
        ("cold", "cold_temperature"),
        ("cold_temperature", "cold_temperature"),
        ("duration", "duration"),
        ("durationMinutes", "duration"),
    ):
        if raw_value.get(source_key) is None:
            continue
        try:
            program[target_key] = _raw_to_float(raw_value[source_key])
        except (TypeError, ValueError):
            continue
    return program


def _clean_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _copy_programs(programs: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    return tuple(dict(program) for program in programs)
