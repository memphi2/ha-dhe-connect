"""Small async helpers shared by the integration."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any


async def cancel_task_if_pending(task: asyncio.Task[Any]) -> None:
    """Cancel and await a task when it has not finished yet."""
    if task.done():
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
