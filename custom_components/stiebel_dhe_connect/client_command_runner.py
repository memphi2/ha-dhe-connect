"""Command execution helpers for the DHE client."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol, TypeVar, cast

from .client_constants import COMMAND_RETRY_ATTEMPTS, COMMAND_RETRY_DELAY_SECONDS
from .client_diagnostics import diagnostic_error as _diagnostic_error
from .client_errors import (
    DHE_COMMAND_EXCEPTIONS as _DHE_COMMAND_EXCEPTIONS,
    runtime_transport_error_or_raise as _runtime_transport_error_or_raise,
)
from .client_types import DHEError, DHESession

_T = TypeVar("_T")


class _DHEClientCommandRunnerContext(Protocol):
    """Client surface required to run commands against the active session."""

    _command_lock: asyncio.Lock
    _ctx: DHESession | None

    async def _ensure_ready(self, timeout: float) -> None:
        """Wait until the client has an active session."""

    async def _force_reconnect(
        self,
        ctx: DHESession | None = None,
        *,
        immediate_availability: bool = False,
        reason: str | None = None,
    ) -> None:
        """Force the active transport session to reconnect."""


def _command_runner_context(client: object) -> _DHEClientCommandRunnerContext:
    """Return the command-runner context for a mixin instance."""

    return cast(_DHEClientCommandRunnerContext, client)


class DHEClientCommandRunnerMixin:
    """Run commands with the client's reconnect and error-mapping policy."""

    async def _run_command_with_reconnect_retry(
        self,
        error_message: str,
        operation: Callable[[DHESession], Awaitable[_T]],
        *,
        timeout: float = 45.0,
        on_error: Callable[[], None] | None = None,
    ) -> _T:
        client = _command_runner_context(self)
        async with client._command_lock:
            for attempt in range(COMMAND_RETRY_ATTEMPTS):
                command_error: Exception
                try:  # noqa: PERF203
                    await client._ensure_ready(timeout=timeout)
                    ctx = client._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    return await operation(ctx)
                except _DHE_COMMAND_EXCEPTIONS as err:  # noqa: PERF203
                    command_error = err
                except RuntimeError as err:
                    command_error = _runtime_transport_error_or_raise(err)
                if on_error is not None:
                    on_error()
                if attempt == 0:
                    await client._force_reconnect(reason=_diagnostic_error(command_error))
                    await asyncio.sleep(COMMAND_RETRY_DELAY_SECONDS)
                    continue
                raise DHEError(f"{error_message}: {command_error}") from command_error
        raise DHEError(error_message)

    async def _run_command_without_reconnect_retry(
        self,
        error_message: str,
        operation: Callable[[DHESession], Awaitable[_T]],
        *,
        timeout: float = 45.0,
    ) -> _T:
        client = _command_runner_context(self)
        async with client._command_lock:
            try:
                await client._ensure_ready(timeout=timeout)
                ctx = client._ctx
                if ctx is None:
                    raise DHEError("DHE session is not connected")
                return await operation(ctx)
            except _DHE_COMMAND_EXCEPTIONS as err:
                raise DHEError(f"{error_message}: {err}") from err
            except RuntimeError as err:
                err = _runtime_transport_error_or_raise(err)
                raise DHEError(f"{error_message}: {err}") from err
