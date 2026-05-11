"""Shared entity helpers for Stiebel DHE Connect."""

from __future__ import annotations

from typing import Any

from .const import DOMAIN


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
