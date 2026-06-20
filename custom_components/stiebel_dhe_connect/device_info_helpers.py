"""Helpers for DHE device identity details."""

from __future__ import annotations

from typing import Any

PRODUCT_ID_PREFIX_LENGTH = 7


def product_id_prefix(value: Any) -> str | None:
    """Return the non-sensitive DHE product ID prefix."""
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    return text[:PRODUCT_ID_PREFIX_LENGTH]
