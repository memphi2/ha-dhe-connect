"""Construct a real DHE client with only the device transport replaced."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from tests.client_test_support import PACKAGE_NAME, _load_client


def make_client(monkeypatch):
    import sys

    module = _load_client()
    monkeypatch.setattr(module, "async_get_clientsession", Mock(return_value=object()))
    client = module.DHEClient(
        SimpleNamespace(loop=asyncio.get_running_loop()),
        "device.invalid",
        8443,
        None,
        "Test",
    )
    client._ctx = module.DHESession(sid="fixture", url_token="fixture")
    client._ensure_ready = AsyncMock()
    client._force_reconnect = AsyncMock()
    client._post_packet = AsyncMock(return_value="ok")
    client._send_ste_command = AsyncMock()
    client._request_app_value = AsyncMock()
    monkeypatch.setattr(
        sys.modules[f"{PACKAGE_NAME}.client_command_runner"],
        "COMMAND_RETRY_DELAY_SECONDS",
        0,
    )
    return client, module
