"""Small async helpers shared by the integration."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant


async def cancel_task_if_pending(task: asyncio.Task[Any]) -> None:
    """Cancel and await a task when it has not finished yet."""
    if task.done():
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def create_background_task(
    hass: HomeAssistant,
    coro: Any,
    name: str,
) -> asyncio.Task[Any]:
    """Create a non-startup-blocking Home Assistant background task."""
    create_task = getattr(hass, "async_create_background_task", None)
    if create_task is not None:
        return create_task(coro, name)
    return hass.async_create_task(coro, name=name)


def task_cancel_callback(task: asyncio.Task[Any]) -> Callable[[], None]:
    """Return an unload callback that cancels a task without returning bool."""

    def _cancel_task() -> None:
        task.cancel()

    return _cancel_task
