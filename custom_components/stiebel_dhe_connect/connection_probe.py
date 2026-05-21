"""Network reachability checks for DHE setup and config flows."""

from __future__ import annotations

import aiohttp
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .connection_helpers import host_for_url

_LOGGER = logging.getLogger(__name__)


async def async_can_connect(
    hass: HomeAssistant,
    host: str,
    port: int,
    *,
    timeout_seconds: int = 8,
) -> bool:
    """Return whether the DHE web endpoint responds on the configured target."""
    should_close = False
    try:
        session = async_get_clientsession(hass)
    except RuntimeError as err:
        # Certain Home Assistant test/runtime environments fail to provide the shared
        # session resolver state at this point in the flow.
        _LOGGER.debug("Falling back to direct aiohttp.ClientSession: %s", err)
        session = aiohttp.ClientSession()
        should_close = True

    url = f"http://{host_for_url(host)}:{port}/"

    try:
        async with session.get(url, timeout=timeout_seconds) as resp:
            await resp.read()
            status = int(resp.status)
            return 200 <= status < 500
    except (aiohttp.ClientError, TimeoutError, OSError):
        return False
    finally:
        if should_close:
            await session.close()
