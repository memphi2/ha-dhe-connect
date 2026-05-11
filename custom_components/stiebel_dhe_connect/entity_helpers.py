"""Shared entity helpers for Stiebel DHE Connect."""

from __future__ import annotations

from typing import Any

from .const import DOMAIN


def build_device_info(host: str, port: int, name: str) -> dict[str, Any]:
    """Build a consistent Home Assistant device_info payload."""
    return {
        "identifiers": {(DOMAIN, f"{host}:{port}")},
        "manufacturer": "STIEBEL ELTRON",
        "model": "DHE Connect",
        "name": name,
    }
