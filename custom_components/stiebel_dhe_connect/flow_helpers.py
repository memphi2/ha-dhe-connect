"""Generic async flow helpers for DHE request/confirm patterns."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar


_T = TypeVar("_T")


async def request_generation_and_wait(
    request: Callable[[], Awaitable[None]],
    generation_getter: Callable[[], int],
    wait_for_generation: Callable[[int], Awaitable[_T]],
) -> _T:
    """Issue a request and wait for the value using the captured generation."""
    generation = int(generation_getter())
    await request()
    return await wait_for_generation(generation)


async def wait_for_or_refresh(
    wait: Callable[[], Awaitable[_T]],
    refresh: Callable[[], Awaitable[None]],
    *,
    retry_exceptions: tuple[type[BaseException], ...],
) -> _T:
    """Wait once, then refresh and wait again when a retryable error occurs."""
    try:
        return await wait()
    except retry_exceptions:
        await refresh()
        return await wait()


async def wait_until(
    predicate: Callable[[], bool],
    *,
    timeout_seconds: float,
    poll_interval_seconds: float = 0.1,
) -> bool:
    """Poll until predicate returns true or timeout is reached."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(poll_interval_seconds)
    return False


async def wait_for_generation_change(
    previous_generation: int,
    generation_getter: Callable[[], int],
    *,
    timeout_seconds: float,
    poll_interval_seconds: float = 0.1,
) -> bool:
    """Wait until a generation counter changes from a previous value."""
    return await wait_until(
        lambda: int(generation_getter()) != previous_generation,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
