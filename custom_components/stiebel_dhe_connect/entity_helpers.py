"""Shared entity helpers for Stiebel DHE Connect."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DOMAIN = "stiebel_dhe_connect"


def build_entity_unique_id(entry_id: str, key: str) -> str:
    """Build a stable unique_id for one entity within a config entry."""
    return f"{DOMAIN}_{entry_id}_{key}"


def build_entity_suggested_object_id(name: str, key: str) -> str:
    """Build a stable suggested entity object id from device name and entity key."""
    device_name = str(name or "").strip() or DOMAIN
    return f"{device_name}_{key}"


def temperature_memory_enabled_default(slot: int) -> bool:
    """Return whether a temperature memory slot is enabled by default."""
    return slot <= 2


def temperature_memory_icon(slot: int) -> str:
    """Return the icon for one temperature memory slot."""
    return f"mdi:numeric-{slot}-box-outline" if slot < 10 else "mdi:counter"


def temperature_memory_measurement_slots(
    slot_measurements: Mapping[int, int],
) -> dict[int, int]:
    """Return a measurement-id-to-slot lookup for temperature memory entities."""
    return {
        measurement_id: slot
        for slot, measurement_id in slot_measurements.items()
    }


def temperature_memory_measurement_slot_items(
    slot_measurements: Mapping[int, int],
) -> tuple[tuple[int, int], ...]:
    """Return temperature memory measurement/slot items sorted by slot."""
    return tuple(
        sorted(
            temperature_memory_measurement_slots(slot_measurements).items(),
            key=lambda item: item[1],
        )
    )


def build_device_info(
    host: str,
    port: int,
    name: str,
    legacy_identifier: str | None = None,
) -> dict[str, Any]:
    """Build a consistent Home Assistant device_info payload."""
    identifiers = {(DOMAIN, f"{host}:{port}")}
    if legacy_identifier:
        identifiers.add((DOMAIN, legacy_identifier))

    return {
        "identifiers": identifiers,
        "manufacturer": "STIEBEL ELTRON",
        "model": "DHE Connect",
        "name": name,
    }


class StiebelDHEEntityMixin:
    """Small shared initializer for DHE entities."""

    def _init_dhe_entity(
        self,
        *,
        entry_id: str,
        key: str,
        name: str,
        client: Any,
    ) -> None:
        """Initialize common entity identity attributes."""
        self._client = client
        self._attr_unique_id = build_entity_unique_id(entry_id, key)
        self._attr_suggested_object_id = build_entity_suggested_object_id(name, key)
        self._attr_device_info = build_device_info(
            client.host,
            client.port,
            name,
            client.legacy_device_identifier,
        )
