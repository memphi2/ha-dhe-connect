"""Tests for DHE reachability probes."""

from __future__ import annotations

import types

import aiohttp
import pytest

from custom_components.stiebel_dhe_connect import connection_probe


class _FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status
        self.read_called = False

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def read(self) -> bytes:
        self.read_called = True
        return b""


class _FakeSession:
    def __init__(self, response: _FakeResponse | BaseException) -> None:
        self.response = response
        self.requested_url: str | None = None
        self.requested_timeout: aiohttp.ClientTimeout | None = None
        self.closed = False

    def get(self, url: str, *, timeout: aiohttp.ClientTimeout) -> _FakeResponse:
        self.requested_url = url
        self.requested_timeout = timeout
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_async_can_connect_accepts_dhe_web_response(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeResponse(204)
    session = _FakeSession(response)
    monkeypatch.setattr(
        connection_probe,
        "async_get_clientsession",
        lambda _hass: session,
    )

    assert await connection_probe.async_can_connect(
        types.SimpleNamespace(),
        "dhe.local",
        8443,
        timeout_seconds=3,
    )
    assert session.requested_url == "http://dhe.local:8443/"
    assert session.requested_timeout is not None
    assert session.requested_timeout.total == 3
    assert response.read_called


@pytest.mark.asyncio
async def test_async_can_connect_rejects_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession(aiohttp.ClientError("offline"))
    monkeypatch.setattr(
        connection_probe,
        "async_get_clientsession",
        lambda _hass: session,
    )

    assert not await connection_probe.async_can_connect(
        types.SimpleNamespace(),
        "dhe.local",
        8443,
    )


@pytest.mark.asyncio
async def test_async_can_connect_falls_back_on_session_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback_session = _FakeSession(_FakeResponse(204))

    def _raise_runtime_error(_hass: object) -> _FakeSession:
        raise RuntimeError("Frame helper not set up")

    monkeypatch.setattr(
        connection_probe,
        "async_get_clientsession",
        _raise_runtime_error,
    )
    monkeypatch.setattr(aiohttp, "ClientSession", lambda: fallback_session)

    assert await connection_probe.async_can_connect(
        types.SimpleNamespace(),
        "dhe.local",
        8443,
    )

    assert fallback_session.requested_url == "http://dhe.local:8443/"
    assert fallback_session.closed
