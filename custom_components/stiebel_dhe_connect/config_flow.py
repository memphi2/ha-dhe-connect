"""Config flow for Stiebel DHE Connect."""

from __future__ import annotations

import ipaddress
import logging
import re
from typing import Any
from urllib.parse import urlsplit

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_PING_INTERVAL,
    CONF_POLL_INTERVAL,
    DEFAULT_NAME,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)


def _normalize_host(host: str) -> str:
    """Normalize and validate the host value from UI input."""
    value = host.strip()
    if not value:
        raise ValueError("empty_host")

    if "://" in value:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("invalid_scheme")
        if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("invalid_host")
        value = parsed.hostname or ""

    value = value.strip().rstrip(".")

    if not value or any(char in value for char in "/?#@\\"):
        raise ValueError("invalid_host")

    # The port has a dedicated config field. Reject host:port to keep URL
    # construction deterministic and avoid ambiguity.
    if ":" in value:
        raise ValueError("embedded_port_or_ipv6_not_supported")

    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass

    if not _HOST_RE.fullmatch(value):
        raise ValueError("invalid_host")

    return value.lower()


def _validate_port(port: int) -> int:
    """Validate TCP port from UI input."""
    port = int(port)
    if port < 1 or port > 65535:
        raise ValueError("invalid_port")
    return port


def _validate_poll_interval(seconds: int) -> int:
    """Validate setpoint polling interval."""
    seconds = int(seconds)
    if seconds < 60:
        raise ValueError("poll_interval_too_low")
    if seconds > 86400:
        raise ValueError("poll_interval_too_high")
    return seconds


def _current_poll_interval(defaults: dict[str, Any]) -> int:
    """Return poll interval with backward compatibility for v0.2/v0.3 entries."""
    return int(defaults.get(CONF_POLL_INTERVAL, defaults.get(CONF_PING_INTERVAL, DEFAULT_POLL_INTERVAL)))


def _apply_validation_error(errors: dict[str, str], err: ValueError) -> None:
    """Map validation exceptions to form fields."""
    code = str(err) or "invalid_host"
    if code == "invalid_port":
        errors[CONF_PORT] = code
    elif code.startswith("poll_interval"):
        errors[CONF_POLL_INTERVAL] = code
    else:
        errors[CONF_HOST] = "invalid_host"


def _schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build config/options schema."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Optional(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): int,
            vol.Optional(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)): str,
            vol.Optional(CONF_POLL_INTERVAL, default=_current_poll_interval(defaults)): int,
        }
    )


async def _can_connect(hass: HomeAssistant, host: str, port: int) -> bool:
    """Check if the DHE web endpoint is reachable before creating the config entry."""
    session = async_get_clientsession(hass)
    url = f"http://{host}:{port}/"

    try:
        async with session.get(url, timeout=8) as resp:
            await resp.read()
            return 200 <= resp.status < 500
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Could not connect to Stiebel DHE at configured endpoint: %s", err)
        return False


class StiebelDHEConnectConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Stiebel DHE Connect."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            try:
                host = _normalize_host(user_input[CONF_HOST])
                port = _validate_port(user_input.get(CONF_PORT, DEFAULT_PORT))
                poll_interval = _validate_poll_interval(user_input.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))
            except ValueError as err:
                _apply_validation_error(errors, err)
            else:
                name = str(user_input.get(CONF_NAME, DEFAULT_NAME)).strip() or DEFAULT_NAME

                if not await _can_connect(self.hass, host, port):
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_create_entry(
                        title=name,
                        data={
                            CONF_HOST: host,
                            CONF_PORT: port,
                            CONF_NAME: name,
                            CONF_POLL_INTERVAL: poll_interval,
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Return the options flow handler."""
        return StiebelDHEConnectOptionsFlow(config_entry)


class StiebelDHEConnectOptionsFlow(config_entries.OptionsFlow):
    """Options flow for Stiebel DHE Connect."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Manage options."""
        current = {**self.config_entry.data, **self.config_entry.options}
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                host = _normalize_host(user_input[CONF_HOST])
                port = _validate_port(user_input.get(CONF_PORT, DEFAULT_PORT))
                poll_interval = _validate_poll_interval(user_input.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))
            except ValueError as err:
                _apply_validation_error(errors, err)
            else:
                name = str(user_input.get(CONF_NAME, DEFAULT_NAME)).strip() or DEFAULT_NAME

                if not await _can_connect(self.hass, host, port):
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_create_entry(
                        title="",
                        data={
                            CONF_HOST: host,
                            CONF_PORT: port,
                            CONF_NAME: name,
                            CONF_POLL_INTERVAL: poll_interval,
                        },
                    )

        return self.async_show_form(
            step_id="init",
            data_schema=_schema(current),
            errors=errors,
        )
