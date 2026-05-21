"""Discovery and setup-pairing helpers for the DHE config flow."""

from __future__ import annotations

from ipaddress import ip_address
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
_MAC_ID_KEYS = (
    "wlan_mac",
    "bluetooth_mac",
    "mac",
    "mac_address",
    "macaddress",
)
_STABLE_ID_KEYS = (
    "device_id",
    "deviceid",
    "serial",
    "serial_no",
    "serial_number",
    "unique_id",
)
_DISPLAY_NAME_PROPERTY_KEYS = (
    "friendly_name",
    "friendlyname",
    "device_name",
    "devicename",
    "name",
    "hostname",
)
_TECHNICAL_DISCOVERY_NAMES = {
    "",
    DOMAIN,
    DOMAIN.replace("_", "-"),
    DHE_ZEROCONF_SERVICE.rstrip("."),
    DHE_ZEROCONF_SERVICE.rstrip(".").replace("_", ""),
    "_ste-dhe",
    "ste-dhe",
}


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


def discovery_identity_candidates(discovery_info: Any) -> tuple[str, ...]:
    """Return normalized stable identity candidates from a Zeroconf payload."""
    candidates: list[str] = []
    for key in _MAC_ID_KEYS:
        mac = normalize_mac(_discovery_identity_value(discovery_info, key))
        if mac:
            candidates.append(mac)
    for key in _STABLE_ID_KEYS:
        stable_id = _normalize_stable_device_id(
            _discovery_identity_value(discovery_info, key)
        )
        if stable_id:
            candidates.append(stable_id)
    return tuple(dict.fromkeys(candidates))


def _discovery_identity_value(discovery_info: Any, key: str) -> Any:
    """Return one identity value from direct attributes or Zeroconf properties."""
    direct = getattr(discovery_info, key, None)
    if direct not in (None, ""):
        return direct
    properties = _discovery_properties(discovery_info)
    value = properties.get(key)
    if value not in (None, ""):
        return value
    return properties.get(key.replace("_", ""))


def _discovery_properties(discovery_info: Any) -> dict[str, str]:
    """Return normalized Zeroconf properties for one discovery payload."""
    raw = (
        getattr(discovery_info, "decoded_properties", None)
        or getattr(discovery_info, "properties", None)
        or {}
    )
    if not isinstance(raw, Mapping):
        return {}
    properties: dict[str, str] = {}
    for key, value in raw.items():
        normalized_key = _normalize_property_text(key)
        normalized_value = _normalize_property_text(value)
        if not normalized_key or not normalized_value:
            continue
        properties[normalized_key] = normalized_value
    return properties


def _normalize_property_text(value: Any) -> str:
    """Return normalized property text from bytes/str Zeroconf fields."""
    if isinstance(value, bytes):
        text = value.decode("utf-8", "ignore")
    else:
        text = str(value or "")
    return text.strip().lower()


def _normalize_stable_device_id(value: Any) -> str | None:
    """Return a normalized non-MAC discovery identity candidate."""
    text = _normalize_property_text(value)
    if not text:
        return None
    text = text.replace(" ", "")
    if len(text) < 6:
        return None
    return text


def coerce_setup_pairing_result(result: Any) -> SetupPairingResult:
    """Accept the current result object and older string/None test doubles."""
    if isinstance(result, SetupPairingResult):
        return result
    if result is None:
        return SetupPairingResult()
    return SetupPairingResult(error_key=str(result))


def discovery_info_name(discovery_info: Any) -> str:
    """Return a human-friendly name from a Zeroconf discovery payload."""
    for raw_name in _discovery_name_candidates(discovery_info):
        if name := _clean_discovery_name(raw_name):
            return name
    return DEFAULT_NAME


def _discovery_name_candidates(discovery_info: Any) -> tuple[Any, ...]:
    """Return display-name candidates ordered by specificity."""
    property_candidates = tuple(
        _discovery_display_property(discovery_info, key)
        for key in _DISPLAY_NAME_PROPERTY_KEYS
    )
    return (
        *property_candidates,
        getattr(discovery_info, "name", None)
        or getattr(discovery_info, "server", None),
        getattr(discovery_info, "hostname", None),
        _host_display_fallback(getattr(discovery_info, "host", None)),
        _host_display_fallback(getattr(discovery_info, "ip_address", None)),
    )


def _discovery_display_property(discovery_info: Any, key: str) -> str | None:
    """Return one raw display property without lowercasing the value."""
    raw = (
        getattr(discovery_info, "decoded_properties", None)
        or getattr(discovery_info, "properties", None)
        or {}
    )
    if not isinstance(raw, Mapping):
        return None
    key_options = {key, key.replace("_", "")}
    for raw_key, raw_value in raw.items():
        if _normalize_property_text(raw_key) in key_options:
            return _decode_property_display_value(raw_value)
    return None


def _decode_property_display_value(value: Any) -> str | None:
    """Return a decoded property value for display-name use."""
    if value in (None, ""):
        return None
    if isinstance(value, bytes):
        text = value.decode("utf-8", "ignore")
    else:
        text = str(value)
    return text.strip() or None


def _clean_discovery_name(raw_name: Any) -> str | None:
    """Return a sanitized device name or None for technical placeholders."""
    if raw_name in (None, ""):
        return None
    name = str(raw_name).strip().rstrip(".")
    service_suffix = f".{DHE_ZEROCONF_SERVICE.rstrip('.')}"
    if name.endswith(service_suffix):
        name = name[: -len(service_suffix)]
    if name.lower().endswith(".local"):
        name = name[:-6]
    name = name.strip().rstrip(".")
    if name.lower() in _TECHNICAL_DISCOVERY_NAMES:
        return None
    if name.lower().endswith("._tcp"):
        return None
    return name or None


def _host_display_fallback(value: Any) -> str | None:
    """Return a last-resort per-target name when discovery has no label."""
    if value in (None, ""):
        return None
    text = str(value).strip().rstrip(".")
    if not text:
        return None
    try:
        ip_address(text)
    except ValueError:
        return text
    return f"{DEFAULT_NAME} {text}"


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
