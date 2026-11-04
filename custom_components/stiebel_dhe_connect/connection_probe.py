"""Network reachability checks for DHE setup and config flows."""

from __future__ import annotations

import logging

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client_types import DHEError
from .connection_helpers import host_for_url
from .http_helpers import (
    IDENTITY_ENCODING_HEADERS,
    WEB_PAGE_RESPONSE_LIMIT,
    read_bounded_response,
)

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
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=timeout_seconds),
            allow_redirects=False,
            auto_decompress=False,
            headers=IDENTITY_ENCODING_HEADERS,
        ) as resp:
            status = int(resp.status)
            if not 200 <= status < 500 or 300 <= status < 400:
                return False
            await read_bounded_response(resp, WEB_PAGE_RESPONSE_LIMIT)
            return True
    except (aiohttp.ClientError, DHEError, TimeoutError, OSError):
        return False
    finally:
        if should_close:
            await session.close()
