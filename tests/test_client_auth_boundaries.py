"""Authentication ordering, rejection, timeout and cancellation contracts."""

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tests.client_behavior_support import make_client
from tests.client_test_support import PACKAGE_NAME

TOKEN = "synthetic-pairing-token-for-tests"


@pytest.fixture
async def device(monkeypatch):
    client, _ = make_client(monkeypatch)
    auth = sys.modules[f"{PACKAGE_NAME}.client_transport_auth"]
    client._load_token = AsyncMock(return_value=TOKEN)
    client._save_token = AsyncMock()
    client._open_session = AsyncMock(return_value=client._ctx)
    client._close_session = AsyncMock()
    client._upgrade_to_websocket = AsyncMock()
    client._notify_pairing_progress = Mock()
    return client, auth


@pytest.mark.parametrize(
    "failure",
    [
        asyncio.CancelledError(),
        OSError("disconnected"),
        RuntimeError("Session is closed"),
    ],
)
async def test_auth_failures_close_session_before_propagation(device, failure):
    client, _ = device
    client._pairing_active = True
    client._read_polling_events_once = AsyncMock(side_effect=failure)
    with pytest.raises(type(failure)):
        await client._open_authenticated_session()
    client._close_session.assert_awaited_once_with(client._ctx)
    client._upgrade_to_websocket.assert_not_awaited()


@pytest.mark.parametrize("event", ["pairing_request", "pairing_result", "__closed"])
async def test_stored_token_rejection_never_starts_silent_pairing(device, event):
    client, auth = device
    client._read_polling_events_once = AsyncMock(
        return_value=[auth.DHEEvent(event, True)]
    )
    with pytest.raises(auth.DHEAuthError, match="reauthentication"):
        await client._open_authenticated_session()
    client._save_token.assert_not_awaited()
    client._close_session.assert_awaited_once_with(client._ctx)


@pytest.mark.parametrize("confirmed,required", [(False, False), (True, True)])
async def test_authenticated_pairing_finishes_only_with_required_confirmation(
    device, confirmed, required
):
    client, _ = device
    client._pairing_active = True
    client._pairing_confirmed_success = confirmed
    client._require_pairing_confirmation = required
    pending, result = await client._handle_authenticated_event(client._ctx)
    assert not pending and result is client._ctx
    assert not client._pairing_active
    client._upgrade_to_websocket.assert_awaited_once_with(client._ctx)


async def test_rejection_wins_over_authenticated_event(device):
    client, auth = device
    client._pairing_failed_explicit = True
    with pytest.raises(auth.DHEError, match="rejected"):
        await client._handle_authenticated_event(client._ctx)
    client._upgrade_to_websocket.assert_not_awaited()


async def test_confirmation_can_arrive_after_authentication(device):
    client, auth = device
    client._require_pairing_confirmation = True
    client._request_initial_token = AsyncMock(return_value=TOKEN)
    client._read_polling_events_once = AsyncMock(
        return_value=[
            auth.DHEEvent("authenticated", None),
            auth.DHEEvent("pairing_result", True),
        ]
    )
    result = await client._open_authenticated_session()
    assert result is client._ctx
    assert not client._require_pairing_confirmation
    client._request_initial_token.assert_awaited_once()
    client._upgrade_to_websocket.assert_awaited_once_with(result)


@pytest.mark.parametrize(
    "stored,pending", [(True, False), (False, False), (False, True)]
)
async def test_auth_deadline_has_distinct_repair_errors(
    device, monkeypatch, stored, pending
):
    client, auth = device
    client._load_token.return_value = TOKEN if stored else ""
    client._request_initial_token = AsyncMock(return_value=TOKEN)
    client._read_polling_events_once = AsyncMock(
        return_value=[auth.DHEEvent("authenticated", None)] if pending else []
    )
    monkeypatch.setattr(
        auth, "time", SimpleNamespace(monotonic=Mock(side_effect=[0, 0, 121]))
    )
    monkeypatch.setattr(
        auth,
        "asyncio",
        SimpleNamespace(sleep=AsyncMock(), CancelledError=asyncio.CancelledError),
    )
    expected = (
        "reauthentication"
        if stored
        else ("confirmation" if pending else "Auth timeout")
    )
    with pytest.raises(auth.DHEError, match=expected):
        await client._open_authenticated_session()
    client._close_session.assert_awaited_once_with(client._ctx)


async def test_missing_initial_token_does_not_open_auth_session(device):
    client, auth = device
    client._load_token.return_value = ""
    client._request_initial_token = AsyncMock(return_value="")
    with pytest.raises(auth.DHEError, match="No token"):
        await client._open_authenticated_session()
    client._open_session.assert_not_awaited()


@pytest.mark.parametrize(
    "failure", [None, OSError("upgrade failed"), RuntimeError("Session is closed")]
)
async def test_manual_pairing_fallback_is_attempted_once_without_early_persistence(
    device, failure
):
    client, auth = device
    client._manual_pairing_requested = True
    client._upgrade_to_websocket.side_effect = failure
    state = auth._TokenRequestState(require_confirmation=True, pairing_confirmed=False)
    for _ in range(2):
        assert (
            await client._handle_token_request_token_response(client._ctx, state, TOKEN)
            is None
        )
    client._upgrade_to_websocket.assert_awaited_once()
    client._post_packet.assert_awaited_once()
    client._save_token.assert_not_awaited()
    client._handle_token_request_pairing_result(state, True)
    assert await client._finalize_confirmed_candidate_token(state) == TOKEN
    client._save_token.assert_awaited_once_with(TOKEN)


@pytest.mark.parametrize("packet", ["__closed", "authenticated", "runtime_error"])
async def test_initial_token_failure_closes_session_without_saving(
    device, monkeypatch, packet
):
    client, auth = device
    client._require_pairing_confirmation = True
    events = [auth.DHEEvent("token_response", TOKEN), auth.DHEEvent(packet, None)]
    client._read_token_request_events_once = AsyncMock(
        return_value=events,
        side_effect=RuntimeError("Session is closed")
        if packet == "runtime_error"
        else None,
    )
    monkeypatch.setattr(
        auth, "time", SimpleNamespace(monotonic=Mock(side_effect=[0, 0, 121]))
    )
    monkeypatch.setattr(
        auth,
        "asyncio",
        SimpleNamespace(sleep=AsyncMock(), CancelledError=asyncio.CancelledError),
    )
    with pytest.raises(RuntimeError if packet == "runtime_error" else auth.DHEError):
        await client._request_initial_token()
    client._save_token.assert_not_awaited()
    client._close_session.assert_awaited_once_with(client._ctx)


async def test_websocket_token_reader_tolerates_poll_timeout(device):
    client, _ = device
    client._ctx.websocket = object()
    client._read_events_once = AsyncMock(side_effect=TimeoutError())
    assert await client._read_token_request_events_once(client._ctx) == []
