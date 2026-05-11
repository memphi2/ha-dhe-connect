"""Shared entity helpers for Stiebel DHE Connect."""

from __future__ import annotations

from typing import Any

DOMAIN = "stiebel_dhe_connect"


def build_entity_unique_id(entry_id: str, key: str) -> str:
    """Build a stable unique_id for one entity within a config entry."""
    return f"{DOMAIN}_{entry_id}_{key}"


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
        self._attr_device_info = build_device_info(
            client.host,
            client.port,
            name,
            client.legacy_device_identifier,
        )
