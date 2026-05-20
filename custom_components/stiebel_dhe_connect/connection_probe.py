"""Network reachability checks for DHE setup and config flows."""

from __future__ import annotations

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .connection_helpers import host_for_url


async def async_can_connect(
    hass: HomeAssistant,
    host: str,
    port: int,
    *,
    timeout_seconds: int = 8,
) -> bool:
    """Return whether the DHE web endpoint responds on the configured target."""
    session = async_get_clientsession(hass)
    url = f"http://{host_for_url(host)}:{port}/"

    try:
        async with session.get(url, timeout=timeout_seconds) as resp:
            await resp.read()
            return 200 <= resp.status < 500
    except (aiohttp.ClientError, TimeoutError, OSError):
        return False
