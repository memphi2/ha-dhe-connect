"""Connection availability state handling for the DHE client."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from .client_connection_supervisor import DHEConnectionSupervisor
from .client_types import AvailabilityCallback, DHESession, OnlineCallback

if TYPE_CHECKING:
    from collections.abc import Callable


class DHEClientConnectionStateMixin:
    """Manage online, availability and reconnect grace state."""

    if TYPE_CHECKING:
        _availability_callbacks: set[AvailabilityCallback]
        _available: bool
        _connection_supervisor: DHEConnectionSupervisor
        _ctx: DHESession | None
        _online: bool
        _online_callbacks: set[OnlineCallback]
        _ready: asyncio.Event
        _reconnect_grace_task: asyncio.Task[None] | None
        _stopped: asyncio.Event

        def _create_background_task(
            self,
            coro: Any,
            name: str,
        ) -> asyncio.Task[Any]: ...

        def _notify_callbacks(
            self,
            callback_name: str,
            callbacks: set[Callable[..., None]],
            *args: Any,
        ) -> None: ...

        def _update_diagnostics(self, **updates: Any) -> None: ...

    def _set_available(self, available: bool, *, immediate: bool = False) -> None:
        if available or immediate:
            self._cancel_reconnect_grace_timer()
        self._emit_availability(available)

    def _emit_availability(self, available: bool) -> None:
        if self._available == available:
            return
        self._available = available
        self._notify_callbacks(
            "availability",
            self._availability_callbacks,
            available,
        )

    def _set_online(self, online: bool) -> None:
        if self._online == online:
            return
        self._online = online
        self._notify_callbacks("online", self._online_callbacks, online)

    def _mark_reconnecting(
        self,
        reason: str,
        *,
        immediate_availability: bool = False,
    ) -> float:
        self._connection_supervisor.mark_disconnected()
        delay = self._connection_supervisor.next_delay()
        self._set_online(False)
        if immediate_availability or self._connection_supervisor.should_mark_unavailable:
            self._set_available(False, immediate=True)
        else:
            self._schedule_reconnect_grace_timer()
        self._update_diagnostics(
            connection_state="reconnecting",
            last_reconnect_reason=reason,
            next_reconnect_delay_seconds=round(delay, 1),
        )
        return delay

    def _schedule_reconnect_grace_timer(self) -> None:
        remaining = self._connection_supervisor.grace_seconds_remaining()
        if remaining is None or remaining <= 0:
            self._set_available(False, immediate=True)
            return
        task = self._reconnect_grace_task
        if task is not None and not task.done():
            return
        self._reconnect_grace_task = self._create_background_task(
            self._expire_reconnect_grace_after(remaining),
            "stiebel_dhe_connect_reconnect_grace_expiry",
        )

    def _cancel_reconnect_grace_timer(self) -> None:
        task = self._reconnect_grace_task
        self._reconnect_grace_task = None
        if task is not None and not task.done():
            task.cancel()

    async def _expire_reconnect_grace_after(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            if (
                self._ctx is None
                and not self._ready.is_set()
                and not self._stopped.is_set()
                and self._connection_supervisor.should_mark_unavailable
            ):
                self._emit_availability(False)
        except asyncio.CancelledError:
            return
        finally:
            if self._reconnect_grace_task is asyncio.current_task():
                self._reconnect_grace_task = None
