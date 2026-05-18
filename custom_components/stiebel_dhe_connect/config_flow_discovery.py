"""Discovery and setup-pairing helpers for the DHE config flow."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant

from .connection_helpers import normalize_host, validate_port
from .const import DEFAULT_NAME, DOMAIN

DHE_ZEROCONF_SERVICE = "_ste-dhe._tcp.local."
FLOW_CONTEXT_DISCOVERED_HOST = "dhe_discovered_host"
FLOW_CONTEXT_DISCOVERED_PORT = "dhe_discovered_port"
FLOW_CONTEXT_DISCOVERY_NAME = "dhe_discovery_name"
FLOW_SOURCE_ZEROCONF = "zeroconf"
SETUP_MODE_MANUAL = "manual"
SETUP_MODE_SCAN = "scan"
ZEROCONF_CHOICE_PREFIX = "zeroconf:"

_MAC_RE = re.compile(r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$")
_COMPACT_MAC_RE = re.compile(r"^[0-9a-f]{12}$")


@dataclass(frozen=True, slots=True)
class SetupPairingResult:
    """Result of a setup pairing probe."""

    error_key: str | None = None
    unique_id: str | None = None


@dataclass(frozen=True, slots=True)
class ZeroconfSetupChoice:
    """One discovered DHE choice shown in the user-started setup flow."""

    key: str
    label: str
    host: str
    port: int
    name: str
    flow_id: str | None


def normalize_mac(value: Any) -> str | None:
    """Return a normalized MAC address or None when the value is unusable."""
    if value in (None, ""):
        return None
    text = str(value).strip().lower().replace("-", ":")
    compact = text.replace(":", "")
    if _COMPACT_MAC_RE.fullmatch(compact):
        return ":".join(compact[index : index + 2] for index in range(0, 12, 2))
    if _MAC_RE.fullmatch(text):
        return text
    return None


def device_unique_id_from_info(device_info: Mapping[str, Any]) -> str | None:
    """Return a MAC-based config-entry unique id from paired device info."""
    for key in ("wlan_mac", "bluetooth_mac"):
        if mac := normalize_mac(device_info.get(key)):
            return mac
    return None


def coerce_setup_pairing_result(result: Any) -> SetupPairingResult:
    """Accept the current result object and older string/None test doubles."""
    if isinstance(result, SetupPairingResult):
        return result
    if result is None:
        return SetupPairingResult()
    return SetupPairingResult(error_key=str(result))


def discovery_info_name(discovery_info: Any) -> str:
    """Return a human-friendly name from a Zeroconf discovery payload."""
    raw_name = (
        getattr(discovery_info, "name", None)
        or getattr(discovery_info, "hostname", None)
        or DEFAULT_NAME
    )
    name = str(raw_name).strip().rstrip(".")
    service_suffix = f".{DHE_ZEROCONF_SERVICE.rstrip('.')}"
    if name.endswith(service_suffix):
        name = name[: -len(service_suffix)]
    if name.lower().endswith(".local"):
        name = name[:-6]
    return name or DEFAULT_NAME


def discovery_context_target(flow: Mapping[str, Any]) -> tuple[str, int] | None:
    """Return the host/port target stored in another discovery flow context."""
    context = flow.get("context")
    if not isinstance(context, Mapping):
        return None
    host_value = context.get(FLOW_CONTEXT_DISCOVERED_HOST)
    port_value = context.get(FLOW_CONTEXT_DISCOVERED_PORT)
    if host_value is None or port_value is None:
        return None
    try:
        return normalize_host(str(host_value)), validate_port(port_value)
    except (TypeError, ValueError):
        return None


def zeroconf_setup_choice_key(host: str, port: int) -> str:
    """Return the setup choice key for one discovered host/port target."""
    return f"{ZEROCONF_CHOICE_PREFIX}{host}:{port}"


def zeroconf_setup_choices_from_progress(
    hass: HomeAssistant,
    *,
    current_flow_id: str | None,
) -> list[ZeroconfSetupChoice]:
    """Return discovered DHE choices from in-progress Zeroconf flows."""
    flow_manager = getattr(hass.config_entries, "flow", None)
    if flow_manager is None:
        return []

    choices: list[ZeroconfSetupChoice] = []
    for flow in flow_manager.async_progress_by_handler(DOMAIN):
        flow_id = flow.get("flow_id")
        if current_flow_id is not None and flow_id == current_flow_id:
            continue
        target = discovery_context_target(flow)
        if target is None:
            continue
        host, port = target
        context = flow.get("context")
        if (
            not isinstance(context, Mapping)
            or context.get("source") != FLOW_SOURCE_ZEROCONF
        ):
            continue
        name = DEFAULT_NAME
        name = str(context.get(FLOW_CONTEXT_DISCOVERY_NAME) or DEFAULT_NAME)
        label = f"{name} ({host}:{port})"
        choices.append(
            ZeroconfSetupChoice(
                key=zeroconf_setup_choice_key(host, port),
                label=label,
                host=host,
                port=port,
                name=name,
                flow_id=str(flow_id) if flow_id is not None else None,
            )
        )
    return sorted(choices, key=lambda choice: (choice.name, choice.host, choice.port))


def is_matching_flow_in_progress(
    hass: HomeAssistant,
    host: str,
    port: int,
    *,
    current_flow_id: str | None,
) -> bool:
    """Return whether another config flow already handles this host/port."""
    flow_manager = getattr(hass.config_entries, "flow", None)
    if flow_manager is None:
        return False
    progress = flow_manager.async_progress_by_handler(DOMAIN)
    for flow in progress:
        if current_flow_id is not None and flow.get("flow_id") == current_flow_id:
            continue
        if discovery_context_target(flow) == (host, port):
            return True
    return False
