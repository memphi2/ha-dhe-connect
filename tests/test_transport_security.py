"""Transport security regressions using loopback HTTP servers only."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import Mock

import aiohttp
import pytest
from aiohttp import web

from tests.test_client_weather_favorites import _load_client


@asynccontextmanager
async def http_server(handler) -> AsyncIterator[str]:
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        yield f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("method", ["get", "post", "version", "scan", "websocket"])
async def test_http_redirect_never_reaches_destination(status: int, method: str) -> None:
    module = _load_client()
    received = []

    async def destination(request):
        received.append(await request.read())
        return web.Response(text="ok")

    async with http_server(destination) as destination_url:
        async def origin(request):
            return web.Response(status=status, headers={"Location": destination_url})

        async with http_server(origin) as origin_url, aiohttp.ClientSession() as session:
            client = module.DHEClient.__new__(module.DHEClient)
            client._session = session
            client.base_url = origin_url
            client._poll_url = lambda *args: origin_url
            client._handle_web_interface_version = Mock()
            if method == "get":
                with pytest.raises(module.DHEError, match=f"GET {status}"):
                    await client._get_text(origin_url)
            elif method == "post":
                with pytest.raises(module.DHEError, match=f"POST {status}"):
                    await client._post_packet(
                        module.DHESession("synthetic-session", "synthetic-token"),
                        '42/1.0.0,["authenticate",{"token":"SYNTHETIC_TEST_TOKEN"}]',
                    )
            elif method == "websocket":
                with pytest.raises(module.DHEError, match="redirect refused"):
                    await client._connect_websocket(origin_url, "synthetic-session")
                assert not session.closed
                assert not session.connector.closed
            elif method == "version":
                await client._request_web_interface_version()
                client._handle_web_interface_version.assert_not_called()
            else:
                from custom_components.stiebel_dhe_connect.setup_scan import _probe_host

                port = int(origin_url.rsplit(":", 1)[1])
                assert await _probe_host(session, "127.0.0.1", port, aiohttp.ClientTimeout(total=2)) is None
    assert received == []
