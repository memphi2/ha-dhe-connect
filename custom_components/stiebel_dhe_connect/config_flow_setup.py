"""Setup-form helpers for the DHE config flow."""

from __future__ import annotations

from ipaddress import IPv4Network
from collections.abc import Mapping
from typing import Any

from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant

from .config_flow_discovery import SETUP_MODE_MANUAL, SETUP_MODE_SCAN
from .connection_helpers import normalize_host, validate_port
from .const import DEFAULT_NAME, DEFAULT_PORT
from .entity_state_helpers import (
    CONF_INTERNAL_SCALD_PROTECTION,
    INTERNAL_SCALD_PROTECTION_OPTIONS,
)
from .error_codes import (
    EMBEDDED_PORT_NOT_SUPPORTED,
    INVALID_HOST,
    INVALID_INTERNAL_SCALD_PROTECTION,
    INVALID_PORT,
    INVALID_SCAN_SUBNET,
)
from .setup_scan import (
    SCAN_SUBNET_PART_CIDR,
    SCAN_SUBNET_PART_NETMASK,
    SCAN_SUBNET_PART_NETWORK_ADDRESS,
    SetupScanSubnetInput,
    split_scan_subnet_suggestions,
)

CONF_SCAN_AUTOMATICALLY = "scan_automatically"
CONF_SCAN_SUBNET_MODE = "scan_subnet_mode"
CONF_SCAN_PORT = "scan_port"
CONF_SCAN_NETWORK_ADDRESS = "scan_network_address"
CONF_SCAN_NETMASK = "scan_netmask"
CONF_SCAN_CIDR = "scan_cidr"
CONF_SETUP_MODE = "setup_mode"
SETUP_SCAN_PROGRESS_ACTION = "scan_dhe"


def apply_validation_error(errors: dict[str, str], err: ValueError) -> None:
    """Map validation exceptions to visible config-flow fields."""
    code = str(err) or INVALID_HOST
    if code == INVALID_PORT:
        errors[CONF_PORT] = code
    elif code == INVALID_INTERNAL_SCALD_PROTECTION:
        errors[CONF_INTERNAL_SCALD_PROTECTION] = code
    elif code == EMBEDDED_PORT_NOT_SUPPORTED:
        errors[CONF_HOST] = code
    else:
        errors[CONF_HOST] = INVALID_HOST


def connection_data_from_user_input(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Return normalized host/port/name/internal-safeguard config data."""
    host = normalize_host(user_input[CONF_HOST])
    port = validate_port(user_input.get(CONF_PORT, DEFAULT_PORT))
    internal_scald_protection = str(
        user_input.get(CONF_INTERNAL_SCALD_PROTECTION) or ""
    ).strip()
    if internal_scald_protection not in INTERNAL_SCALD_PROTECTION_OPTIONS:
        raise ValueError(INVALID_INTERNAL_SCALD_PROTECTION)
    name = str(user_input.get(CONF_NAME, DEFAULT_NAME)).strip() or DEFAULT_NAME
    return {
        CONF_HOST: host,
        CONF_PORT: port,
        CONF_NAME: name,
        CONF_INTERNAL_SCALD_PROTECTION: internal_scald_protection,
    }


def scan_subnet_network_mask_input(
    user_input: Mapping[str, Any],
) -> SetupScanSubnetInput:
    """Return normalized network-address and subnet-mask input."""
    return SetupScanSubnetInput(
        network_address=str(user_input.get(CONF_SCAN_NETWORK_ADDRESS) or "").strip(),
        netmask=str(user_input.get(CONF_SCAN_NETMASK) or "").strip(),
    )


def scan_subnet_cidr_input(user_input: Mapping[str, Any]) -> SetupScanSubnetInput:
    """Return normalized CIDR-only subnet input."""
    return SetupScanSubnetInput(cidr=str(user_input.get(CONF_SCAN_CIDR) or "").strip())


def scan_subnet_network_mask_error_field(scan_input: SetupScanSubnetInput) -> str:
    """Return a visible network-mask form field for subnet validation errors."""
    if not scan_input.network_address:
        return CONF_SCAN_NETWORK_ADDRESS
    return CONF_SCAN_NETMASK


def required_scan_subnet(scan_input: SetupScanSubnetInput) -> IPv4Network:
    """Return the selected subnet from a mode-specific required subnet form."""
    scan_subnet = scan_input.parse()
    if scan_subnet is None:
        raise ValueError(INVALID_SCAN_SUBNET)
    return scan_subnet


def scan_subnet_suggested_values(network: IPv4Network) -> dict[str, str]:
    """Return split setup-scan form suggestions for one IPv4 network."""
    suggestions = split_scan_subnet_suggestions(network)
    return {
        CONF_SCAN_NETWORK_ADDRESS: suggestions[SCAN_SUBNET_PART_NETWORK_ADDRESS],
        CONF_SCAN_NETMASK: suggestions[SCAN_SUBNET_PART_NETMASK],
        CONF_SCAN_CIDR: suggestions[SCAN_SUBNET_PART_CIDR],
    }


def language_from_hass(hass: HomeAssistant) -> str:
    """Return the configured Home Assistant language."""
    return str(getattr(hass.config, "language", "") or "")


def setup_mode_labels(language: str) -> dict[str, str]:
    """Return static setup method labels for the initial setup form."""
    if language.lower().startswith("de"):
        return {
            SETUP_MODE_SCAN: "Subnetz-Scan",
            SETUP_MODE_MANUAL: "Manuell eingeben",
        }
    return {
        SETUP_MODE_SCAN: "Subnet scan",
        SETUP_MODE_MANUAL: "Enter manually",
    }
