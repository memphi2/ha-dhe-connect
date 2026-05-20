"""Helpers for surfacing failed DHE actions to Home Assistant."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .client_types import DHEError


def dhe_action_error(message: str, err: DHEError) -> HomeAssistantError:
    """Return the Home Assistant exception for a failed DHE-backed action."""
    return HomeAssistantError(f"{message}: {err}")


async def run_dhe_action(action: Awaitable[Any], message: str) -> Any:
    """Run one DHE-backed action and expose DHE failures to Home Assistant."""
    try:
        return await action
    except DHEError as err:
        raise dhe_action_error(message, err) from err
