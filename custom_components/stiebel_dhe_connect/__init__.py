"""Stiebel DHE Connect custom integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant

from .client import DHEClient
from .const import (
    DEFAULT_NAME,
    DEFAULT_PORT,
    DOMAIN,
    PLATFORMS,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class DHEConnectRuntimeData:
    """Runtime data for the integration."""

    client: DHEClient
    name: str


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Stiebel DHE Connect from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    data = {**entry.data, **entry.options}
    host = data[CONF_HOST]
    port = int(data.get(CONF_PORT, DEFAULT_PORT))
    name = data.get(CONF_NAME, DEFAULT_NAME)

    token_file = ".storage/stiebel_dhe_connect_token.txt"

    client = DHEClient(
        hass=hass,
        host=host,
        port=port,
        token_file=token_file,
        name="Home Assistant",
    )

    hass.data[DOMAIN][entry.entry_id] = DHEConnectRuntimeData(
        client=client,
        name=name,
    )

    _start_client_background(hass, client)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if runtime is not None:
        await runtime.client.stop()

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _start_client_background(hass: HomeAssistant, client: DHEClient) -> None:
    """Start the persistent DHE session without blocking entity setup."""
    create_background_task = getattr(hass, "async_create_background_task", None)
    if create_background_task is not None:
        create_background_task(client.start(), "stiebel_dhe_connect_start")
    else:
        hass.async_create_task(client.start(), name="stiebel_dhe_connect_start")
