"""Authentication and pairing handshake helpers for the DHE transport."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import logging
import time
from typing import TYPE_CHECKING, Any

from .client_constants import AUTH_POLL_TIMEOUT_SECONDS
from .client_diagnostics import (
    diagnostic_error as _diagnostic_error,
    summarize_diagnostic_value as _summarize_diagnostic_value,
)
from .client_errors import (
    DHE_TRANSPORT_EXCEPTIONS as _DHE_TRANSPORT_EXCEPTIONS,
    runtime_transport_error_or_raise as _runtime_transport_error_or_raise,
)
from .client_types import DHEAuthError, DHEError, DHEEvent, DHESession, DHESessionClosed
from .pairing_helpers import pairing_result_success as _pairing_result_success

_LOGGER = logging.getLogger(__name__)


@dataclass
class _TokenRequestState:
    """Mutable state while waiting for DHE token/pairing handshake events."""

    require_confirmation: bool
    pairing_confirmed: bool
    saw_pairing_request: bool = False
    candidate_token: str | None = None
    manual_auth_sent: bool = False
    manual_websocket_attempted: bool = False


class DHEClientTransportAuthMixin:
    """Authenticate DHE sessions and coordinate pairing-token handshakes."""

    if TYPE_CHECKING:
        name: str
        _manual_pairing_requested: bool
        _pairing_active: bool
        _pairing_confirmed_success: bool
        _pairing_failed_explicit: bool
        _pairing_request_seen: bool
        _pause_auto_reconnect_for_pairing: bool
        _require_pairing_confirmation: bool
        _stopped: asyncio.Event

        async def _load_token(self) -> str: ...

        async def _save_token(self, token: str) -> None: ...

        async def _open_session(self, token_for_url: str) -> DHESession: ...

        async def _close_session(self, ctx: DHESession) -> None: ...

        async def _upgrade_to_websocket(self, ctx: DHESession) -> None: ...

        async def _read_events_once(self, ctx: DHESession) -> list[DHEEvent]: ...

        async def _read_polling_events_once(
            self,
            ctx: DHESession,
        ) -> list[DHEEvent]: ...

        async def _post_packet(self, ctx: DHESession, packet: str) -> str: ...

        def _event_packet(self, event: str, data: Any) -> str: ...

        def _record_pairing_progress(
            self,
            state: str,
            message: str,
            *,
            notify: bool = False,
            result: Any | None = None,
        ) -> None: ...

        def _record_pairing_requested(self) -> None: ...

        def _record_pairing_result(self, result: Any) -> None: ...

        def _record_pairing_failed(self, error: BaseException) -> None: ...

        def _notify_callbacks(
            self,
            callback_name: str,
            callbacks: set[Callable[..., None]],
            *args: Any,
        ) -> None: ...

    def _prepare_auth_session_token(self, token: str) -> tuple[str, bool]:
        """Normalize authentication token usage and return stored-token flag."""
        if self._require_pairing_confirmation and token:
            _LOGGER.warning(
                "Pairing confirmation is required; ignoring existing token and "
                "requesting a fresh one."
            )
            token = ""
        using_stored_token = bool(token) and not self._require_pairing_confirmation
        return token, using_stored_token

    def _start_token_pairing_request(self) -> None:
        """Initialize pairing state before requesting a fresh token."""
        self._pairing_active = True
        self._require_pairing_confirmation = True
        self._pairing_request_seen = False
        self._pairing_confirmed_success = False
        self._pairing_failed_explicit = False
        self._record_pairing_progress(
            "requesting_token",
            "No stored DHE token; requesting a new pairing token.",
            notify=True,
        )

    def _is_token_response_event(self, event: DHEEvent) -> bool:
        """Return True when event carries a likely DHE token."""
        return (
            event.name == "token_response"
            and isinstance(event.data, str)
            and len(event.data) > 20
        )

    async def _handle_auth_token_response(self, ctx: DHESession, token: str) -> None:
        """Persist a new token and send authenticate for current auth session."""
        _LOGGER.debug(
            "DHE auth event: token_response "
            "(pairing_active=%s, require_confirmation=%s, pairing_confirmed=%s)",
            self._pairing_active,
            self._require_pairing_confirmation,
            self._pairing_confirmed_success,
        )
        await self._save_token(token)
        if self._pairing_active:
            self._record_pairing_progress(
                "token_received",
                "DHE pairing token received.",
                notify=True,
            )
        await self._post_packet(
            ctx,
            self._event_packet("authenticate", {"token": token}),
        )

    def _raise_closed_auth_session(self, *, using_stored_token: bool) -> None:
        """Raise the appropriate auth/session error for a closed socket."""
        if using_stored_token:
            raise DHEAuthError(
                "Stored DHE token was not accepted; reauthentication is required"
            )
        raise DHESessionClosed("DHE closed Socket.IO session during authentication")

    async def _handle_authenticated_event(
        self,
        ctx: DHESession,
    ) -> tuple[bool, DHESession | None]:
        """Handle an authenticated event and return pending/complete state."""
        _LOGGER.debug(
            "DHE auth event: authenticated "
            "(pairing_active=%s, require_confirmation=%s, pairing_confirmed=%s)",
            self._pairing_active,
            self._require_pairing_confirmation,
            self._pairing_confirmed_success,
        )
        if self._pairing_failed_explicit:
            raise DHEError("Pairing was rejected on the DHE")
        if self._pairing_active:
            if self._require_pairing_confirmation and not self._pairing_confirmed_success:
                self._record_pairing_progress(
                    "authenticated_pending_confirmation",
                    "Authenticated, waiting for device pairing confirmation.",
                    notify=True,
                )
                return True, None
            if not self._require_pairing_confirmation and not self._pairing_confirmed_success:
                self._record_pairing_progress(
                    "authenticated_without_device_confirmation",
                    "DHE authentication completed without on-device pairing confirmation request.",
                    notify=True,
                )
                self._pairing_active = False
                self._pause_auto_reconnect_for_pairing = False
                await self._upgrade_to_websocket(ctx)
                return False, ctx
            self._record_pairing_progress(
                "authenticated",
                "DHE pairing and authentication completed.",
                notify=True,
            )
            self._pairing_active = False
            self._require_pairing_confirmation = False
            self._manual_pairing_requested = False
            self._pause_auto_reconnect_for_pairing = False
        await self._upgrade_to_websocket(ctx)
        return False, ctx

    def _handle_auth_pairing_request_event(self, *, using_stored_token: bool) -> None:
        """Handle pairing_request during auth loop."""
        _LOGGER.debug("DHE auth event: pairing_request")
        if using_stored_token:
            raise DHEAuthError(
                "Stored DHE token is no longer paired with this DHE; "
                "reauthentication is required"
            )
        self._record_pairing_requested()

    def _handle_auth_pairing_result_event(
        self,
        result: Any,
        *,
        using_stored_token: bool,
    ) -> None:
        """Handle pairing_result during auth loop."""
        _LOGGER.info(
            "DHE auth event: pairing_result=%s",
            _summarize_diagnostic_value(result),
        )
        if using_stored_token:
            raise DHEAuthError(
                "Stored DHE token triggered DHE pairing confirmation; "
                "reauthentication is required"
            )
        self._record_pairing_result(result)

    async def _finalize_pending_authenticated_session(
        self,
        ctx: DHESession,
        *,
        authenticated_received: bool,
    ) -> DHESession | None:
        """Upgrade once pairing confirmation arrives after authenticated."""
        if not (
            authenticated_received
            and self._pairing_active
            and self._require_pairing_confirmation
            and self._pairing_confirmed_success
        ):
            return None
        self._record_pairing_progress(
            "authenticated",
            "DHE pairing and authentication completed.",
            notify=True,
        )
        self._pairing_active = False
        self._require_pairing_confirmation = False
        self._pause_auto_reconnect_for_pairing = False
        await self._upgrade_to_websocket(ctx)
        return ctx

    async def _open_authenticated_session(
        self,
        *,
        token_request_timeout_seconds: float = 120.0,
    ) -> DHESession:
        token = await self._load_token()
        token, using_stored_token = self._prepare_auth_session_token(token)
        if not token:
            _LOGGER.info(
                "No stored DHE token. Requesting new token; confirm pairing on DHE if prompted."
            )
            self._start_token_pairing_request()
            token = await self._request_initial_token(
                timeout_seconds=token_request_timeout_seconds,
            )
            if not token:
                raise DHEError("No token received. Pairing may be required on the DHE.")
        ctx = await self._open_session(token)
        try:
            await self._post_packet(
                ctx,
                self._event_packet(
                    "token_request",
                    {"token": token, "name": self.name},
                ),
            )
            deadline = time.monotonic() + 120.0
            authenticated_received = False
            while time.monotonic() < deadline and not self._stopped.is_set():
                for event in await self._read_polling_events_once(ctx):
                    if event.name == "__closed":
                        self._raise_closed_auth_session(using_stored_token=using_stored_token)
                    if self._is_token_response_event(event):
                        await self._handle_auth_token_response(ctx, str(event.data))
                    elif event.name == "authenticated":
                        pending_confirmation, session = await self._handle_authenticated_event(
                            ctx
                        )
                        authenticated_received = (
                            authenticated_received or pending_confirmation
                        )
                        if session is not None:
                            return session
                    elif event.name == "pairing_request":
                        self._handle_auth_pairing_request_event(
                            using_stored_token=using_stored_token
                        )
                    elif event.name == "pairing_result":
                        self._handle_auth_pairing_result_event(
                            event.data,
                            using_stored_token=using_stored_token,
                        )
                session = await self._finalize_pending_authenticated_session(
                    ctx,
                    authenticated_received=authenticated_received,
                )
                if session is not None:
                    return session
                await asyncio.sleep(0.25)
            if authenticated_received and self._require_pairing_confirmation:
                raise DHEError(
                    "Authenticated, but DHE pairing confirmation was not completed in time"
                )
            if using_stored_token:
                raise DHEAuthError(
                    "Stored DHE token was not accepted; reauthentication is required"
                )
            raise DHEError("Auth timeout: no authenticated event received")
        except asyncio.CancelledError:
            await self._close_session(ctx)
            raise
        except _DHE_TRANSPORT_EXCEPTIONS as err:
            if self._pairing_active:
                self._record_pairing_failed(err)
            await self._close_session(ctx)
            raise
        except RuntimeError as err:
            transport_err = _runtime_transport_error_or_raise(err)
            if self._pairing_active:
                self._record_pairing_failed(transport_err)
            await self._close_session(ctx)
            raise

    async def _read_token_request_events_once(self, ctx: DHESession) -> list[DHEEvent]:
        """Read one token-request event batch from websocket or polling transport."""
        try:
            if ctx.websocket is not None:
                return await asyncio.wait_for(
                    self._read_events_once(ctx),
                    timeout=AUTH_POLL_TIMEOUT_SECONDS,
                )
            return await self._read_polling_events_once(ctx)
        except TimeoutError:
            return []

    async def _persist_received_token(self, token: str) -> str:
        """Record and persist a newly received DHE token."""
        self._record_pairing_progress(
            "token_received",
            "DHE pairing token received.",
            notify=True,
        )
        await self._save_token(token)
        return token

    def _handle_token_request_pairing_result(
        self,
        state: _TokenRequestState,
        result: Any,
    ) -> None:
        """Apply pairing_result payload to token request state."""
        _LOGGER.info(
            "DHE event: pairing_result=%s",
            _summarize_diagnostic_value(result),
        )
        self._record_pairing_result(result)
        if not state.require_confirmation:
            return
        success = _pairing_result_success(result)
        if success is False:
            raise DHEError("Pairing confirmation rejected on DHE")
        if success is True:
            state.pairing_confirmed = True

    async def _maybe_authenticate_manual_pairing_token(
        self,
        ctx: DHESession,
        state: _TokenRequestState,
        token: str,
    ) -> None:
        """Handle manual-pairing fallback when no pairing_request event was seen."""
        if not self._manual_pairing_requested:
            _LOGGER.debug(
                "Token received without pairing_request; waiting for "
                "explicit pairing confirmation events."
            )
            return
        if not state.manual_auth_sent:
            state.manual_auth_sent = True
            _LOGGER.info(
                "Manual pairing token received; authenticating "
                "same session while waiting for explicit pairing_result."
            )
            await self._post_packet(
                ctx,
                self._event_packet("authenticate", {"token": token}),
            )
        if state.manual_websocket_attempted:
            _LOGGER.debug(
                "Token received without pairing_request during manual pairing; "
                "waiting for explicit pairing_result from DHE."
            )
            return
        state.manual_websocket_attempted = True
        try:
            await self._upgrade_to_websocket(ctx)
            _LOGGER.debug(
                "Manual pairing session upgraded to websocket "
                "while waiting for pairing_result."
            )
        except _DHE_TRANSPORT_EXCEPTIONS as err:
            _LOGGER.debug(
                "Manual pairing websocket upgrade unavailable; "
                "continuing polling while waiting for pairing_result: %s",
                _diagnostic_error(err),
            )
        except RuntimeError as err:
            transport_err = _runtime_transport_error_or_raise(err)
            _LOGGER.debug(
                "Manual pairing websocket upgrade unavailable; "
                "continuing polling while waiting for pairing_result: %s",
                _diagnostic_error(transport_err),
            )
        _LOGGER.debug(
            "Token received without pairing_request during manual pairing; "
            "waiting for explicit pairing_result from DHE."
        )

    async def _handle_token_request_token_response(
        self,
        ctx: DHESession,
        state: _TokenRequestState,
        token: str,
    ) -> str | None:
        """Handle token_response and return token once it is fully accepted."""
        _LOGGER.debug(
            "DHE event: token_response "
            "(require_confirmation=%s, saw_pairing_request=%s, pairing_confirmed=%s)",
            state.require_confirmation,
            state.saw_pairing_request,
            state.pairing_confirmed,
        )
        state.candidate_token = token
        if not state.require_confirmation:
            return await self._persist_received_token(token)
        if state.pairing_confirmed:
            _LOGGER.debug(
                "Token received after explicit pairing confirmation "
                "(saw_pairing_request=%s).",
                state.saw_pairing_request,
            )
            return await self._persist_received_token(token)
        if not state.saw_pairing_request:
            await self._maybe_authenticate_manual_pairing_token(ctx, state, token)
            return None
        _LOGGER.debug("Token received, waiting for DHE pairing confirmation.")
        return None

    async def _finalize_confirmed_candidate_token(
        self,
        state: _TokenRequestState,
    ) -> str | None:
        """Persist a previously received token once pairing confirmation arrives."""
        if not (
            state.require_confirmation
            and state.candidate_token
            and state.pairing_confirmed
        ):
            return None
        _LOGGER.debug(
            "Pairing confirmed after token_response; proceeding "
            "(saw_pairing_request=%s).",
            state.saw_pairing_request,
        )
        return await self._persist_received_token(state.candidate_token)

    async def _request_initial_token(self, *, timeout_seconds: float = 120.0) -> str:
        ctx = await self._open_session("")
        state = _TokenRequestState(
            require_confirmation=self._require_pairing_confirmation,
            pairing_confirmed=not self._require_pairing_confirmation,
        )
        try:
            _LOGGER.debug(
                "DHE token request started (require_confirmation=%s).",
                state.require_confirmation,
            )
            await self._post_packet(
                ctx,
                self._event_packet(
                    "token_request",
                    {"token": "", "name": self.name},
                ),
            )
            token_timeout = max(1.0, float(timeout_seconds))
            deadline = time.monotonic() + token_timeout
            while time.monotonic() < deadline and not self._stopped.is_set():
                events = await self._read_token_request_events_once(ctx)
                for event in events:
                    if event.name == "__closed":
                        raise DHESessionClosed(
                            "DHE closed Socket.IO session while requesting token"
                        )
                    if event.name == "authenticated":
                        _LOGGER.debug(
                            "DHE event: authenticated while waiting for pairing_result "
                            "(pairing_confirmed=%s).",
                            state.pairing_confirmed,
                        )
                        continue
                    if event.name == "pairing_request":
                        _LOGGER.debug("DHE event: pairing_request")
                        state.saw_pairing_request = True
                        self._record_pairing_requested()
                        continue
                    if event.name == "pairing_result":
                        self._handle_token_request_pairing_result(state, event.data)
                        continue
                    if self._is_token_response_event(event):
                        token = await self._handle_token_request_token_response(
                            ctx,
                            state,
                            str(event.data),
                        )
                        if token is not None:
                            return token
                token = await self._finalize_confirmed_candidate_token(state)
                if token is not None:
                    return token
                await asyncio.sleep(0.3)
            if state.require_confirmation and state.candidate_token:
                raise DHEError(
                    "Token received but DHE pairing confirmation did not complete in time"
                )
            raise DHEError("Token request timeout")
        except _DHE_TRANSPORT_EXCEPTIONS as err:
            self._record_pairing_failed(err)
            raise
        except RuntimeError as err:
            transport_err = _runtime_transport_error_or_raise(err)
            self._record_pairing_failed(transport_err)
            raise
        finally:
            await self._close_session(ctx)
