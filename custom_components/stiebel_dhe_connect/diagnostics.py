"""Diagnostics support for Stiebel DHE Connect."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant

from .client_diagnostics import redact_diagnostic_text, summarize_diagnostic_value
from .config_entry_helpers import merged_entry_data
from .const import DEFAULT_PORT, DOMAIN

TO_REDACT = {
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
    "access_token",
    "address",
    "addresses",
    "api_key",
    "auth",
    "auth_token",
    "authorization",
    "bearer",
    "bluetooth",
    "bluetooth_mac",
    "bssid",
    "cidr",
    "client_secret",
    "code",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "device_id",
    "email",
    "entry_id",
    "host",
    "hostname",
    "ip",
    "key",
    "local_ip",
    "mac",
    "name",
    "netmask",
    "network",
    "network_address",
    "pairing_code",
    "password",
    "pin",
    "port",
    "refresh_token",
    "serial",
    "secret",
    "session_id",
    "sid",
    "scan_cidr",
    "scan_netmask",
    "scan_network_address",
    "scan_networks",
    "scan_subnet",
    "ssid",
    "subnet",
    "token",
    "token_file",
    "token_path",
    "unique_id",
    "url_token",
    "user",
    "username",
    "websocket_sid",
    "wlan",
    "wlan_mac",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return anonymized diagnostics for one config entry."""
    merged = merged_entry_data(entry)
    port = _coerce_port(merged.get(CONF_PORT))
    data: dict[str, Any] = {
        "integration": {
            "domain": DOMAIN,
            "diagnostics_schema": 1,
        },
        "config_entry": {
            "source": getattr(entry, "source", None),
            "version": getattr(entry, "version", None),
            "minor_version": getattr(entry, "minor_version", None),
            "has_unique_id": bool(getattr(entry, "unique_id", None)),
            "data": dict(getattr(entry, "data", {}) or {}),
            "options": dict(getattr(entry, "options", {}) or {}),
            "target": {
                "has_host": bool(str(merged.get(CONF_HOST, "")).strip()),
                "uses_default_port": port == DEFAULT_PORT if port is not None else None,
                "custom_port": port is not None and port != DEFAULT_PORT,
            },
        },
        "runtime": _runtime_diagnostics(hass, entry),
    }
    return _anonymize(data)


def _runtime_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    client = getattr(runtime, "client", None)
    if client is None:
        return {"loaded": False}

    last_measurements = _mapping_from(getattr(client, "last_measurements", {}))
    last_app_values = _mapping_from(getattr(client, "last_app_values", {}))
    last_device_info = _mapping_from(getattr(client, "last_device_info", {}))
    last_radio_state = _mapping_from(getattr(client, "last_radio_state", {}))
    last_weather_state = _mapping_from(getattr(client, "last_weather_state", {}))

    return {
        "loaded": True,
        "connection": {
            "available": bool(getattr(client, "available", False)),
            "online": bool(getattr(client, "online", False)),
            "reconnect_count": _coerce_int(getattr(client, "reconnect_count", 0)),
            "diagnostic_state": summarize_diagnostic_value(
                _mapping_from(getattr(client, "diagnostic_state", {}))
            ),
        },
        "cache": {
            "measurement_count": len(last_measurements),
            "measurement_ids": sorted(str(key) for key in last_measurements),
            "app_value_count": len(last_app_values),
            "app_value_keys": sorted(str(key) for key in last_app_values),
            "device_info_keys": sorted(str(key) for key in last_device_info),
            "radio_state_keys": sorted(str(key) for key in last_radio_state),
            "weather_state_keys": sorted(str(key) for key in last_weather_state),
        },
    }


def _mapping_from(value: object) -> Mapping[Any, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _coerce_port(value: object) -> int | None:
    if not isinstance(value, int | str):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: object) -> int:
    if not isinstance(value, int | float | str):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _anonymize(value: dict[str, Any]) -> dict[str, Any]:
    return _redact_private_text(async_redact_data(value, TO_REDACT))


def _redact_private_text(value: Any) -> Any:
    if isinstance(value, str):
        if value == REDACTED:
            return value
        return redact_diagnostic_text(value)
    if isinstance(value, list):
        return [_redact_private_text(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_private_text(item) for item in value)
    if isinstance(value, Mapping):
        return {
            redact_diagnostic_text(key): _redact_private_text(item)
            for key, item in value.items()
        }
    return value
