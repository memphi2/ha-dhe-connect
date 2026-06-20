"""Shared entity helpers for DHE Connect."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.helpers.device_registry import DeviceInfo

DOMAIN = "stiebel_dhe_connect"
DEFAULT_DEVICE_MODEL = "DHE Connect"


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


def device_registry_model(device_info: Mapping[str, Any] | None = None) -> str:
    """Return the HA device-registry model from DHE runtime metadata."""
    if device_info is None:
        return DEFAULT_DEVICE_MODEL
    return _clean_device_info_text(device_info.get("device_type")) or DEFAULT_DEVICE_MODEL


def device_registry_sw_version(
    device_info: Mapping[str, Any] | None = None,
) -> str | None:
    """Return the HA device-registry firmware version from DHE runtime metadata."""
    if device_info is None:
        return None
    return _clean_device_info_text(device_info.get("protocol_version"))


def _clean_device_info_text(value: Any) -> str | None:
    """Return a non-empty DeviceInfo text value."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def build_device_info(
    host: str,
    port: int,
    name: str,
    stable_identifier: str | None = None,
    runtime_device_info: Mapping[str, Any] | None = None,
) -> DeviceInfo:
    """Build a consistent Home Assistant device_info payload."""
    identifiers = {(DOMAIN, stable_identifier or f"{host}:{port}")}

    device_info: DeviceInfo = {
        "identifiers": identifiers,
        "model": device_registry_model(runtime_device_info),
        "name": name,
    }
    if sw_version := device_registry_sw_version(runtime_device_info):
        device_info["sw_version"] = sw_version
    return device_info


class StiebelDHEEntityMixin:
    """Small shared initializer for DHE entities."""

    _attr_device_info: DeviceInfo | None
    _attr_suggested_object_id: str | None
    _attr_unique_id: str | None
    _client: Any

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
            getattr(client, "device_identifier", None) or f"entry:{entry_id}",
            getattr(client, "last_device_info", None),
        )
