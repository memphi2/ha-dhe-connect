"""Diagnostics support for DHE Connect."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant

from .client_diagnostics import redact_diagnostic_text, summarize_diagnostic_value
from .config_entry_helpers import merged_entry_data
from .connection_helpers import validate_port
from .const import DEFAULT_PORT, DOMAIN
from .device_info_helpers import product_id_prefix
from .discovery_state import async_load_discovery_cache, discovery_health_diagnostics

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
    "ip_address",
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
    "service_name",
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
    await async_load_discovery_cache(hass)
    merged = merged_entry_data(entry)
    raw_port = merged.get(CONF_PORT)
    if raw_port is None:
        port = None
    else:
        try:
            port = validate_port(raw_port)
        except (TypeError, ValueError):
            port = None
    has_host = bool(str(merged.get(CONF_HOST, "")).strip())
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
                "has_host": has_host,
                "uses_default_port": port == DEFAULT_PORT if port is not None else None,
                "custom_port": port is not None and port != DEFAULT_PORT,
            },
        },
        "runtime": _runtime_diagnostics(hass, entry),
        "discovery": discovery_health_diagnostics(hass),
    }
    return _anonymize(data)


def _runtime_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    del hass
    runtime = getattr(entry, "runtime_data", None)
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
            "reconnect_supervisor": summarize_diagnostic_value(
                _mapping_from(getattr(client, "reconnect_supervisor_state", {}))
            ),
        },
        "transport": _transport_diagnostics(
            _mapping_from(getattr(client, "transport_statistics", {}))
        ),
        "runtime_parser": _parser_diagnostics(
            _mapping_from(getattr(client, "runtime_parser_statistics", {}))
        ),
        "cache": {
            "measurement_count": len(last_measurements),
            "measurement_ids": sorted(str(key) for key in last_measurements),
            "app_value_count": len(last_app_values),
            "app_value_keys": sorted(str(key) for key in last_app_values),
            "device_info_keys": sorted(str(key) for key in last_device_info),
            "radio_state_keys": sorted(str(key) for key in last_radio_state),
            "weather_state_keys": sorted(str(key) for key in last_weather_state),
        },
        "device": _device_diagnostics(last_device_info),
    }


def _mapping_from(value: object) -> Mapping[Any, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _coerce_int(value: object) -> int:
    if not isinstance(value, int | float | str):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _device_diagnostics(device_info: Mapping[Any, Any]) -> dict[str, Any]:
    product_prefix = device_info.get("product_id_prefix")
    if product_prefix in (None, ""):
        product_prefix = product_id_prefix(device_info.get("device_id"))

    return {
        "has_device_info": bool(device_info),
        "device_type": device_info.get("device_type"),
        "product_id_prefix": product_prefix,
        "protocol_version": device_info.get("protocol_version"),
        "web_app_version": device_info.get("web_app_version"),
        "raw_odb_protocol_version": device_info.get("raw_odb_protocol_version"),
        "has_wlan_mac": bool(device_info.get("wlan_mac")),
        "has_bluetooth_mac": bool(device_info.get("bluetooth_mac")),
    }


def _parser_diagnostics(statistics: Mapping[Any, Any]) -> dict[str, Any]:
    counts = _mapping_from(statistics.get("counts"))
    return {
        "message_count": _coerce_int(statistics.get("message_count")),
        "last_category": statistics.get("last_category"),
        "category_counts": {
            str(key): _coerce_int(value)
            for key, value in sorted(counts.items(), key=lambda item: str(item[0]))
        },
    }


def _transport_diagnostics(statistics: Mapping[Any, Any]) -> dict[str, Any]:
    return {
        "websocket_upgrade_failures": _coerce_int(
            statistics.get("websocket_upgrade_failures")
        ),
    }


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
