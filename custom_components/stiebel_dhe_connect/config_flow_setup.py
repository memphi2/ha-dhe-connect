"""Setup-form helpers for the DHE config flow."""

from __future__ import annotations

from ipaddress import IPv4Network
from typing import Any

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from .config_flow_discovery import SETUP_MODE_MANUAL, SETUP_MODE_SCAN
from .entity_state_helpers import CONF_INTERNAL_SCALD_PROTECTION
from .setup_scan import (
    SCAN_SUBNET_PART_CIDR,
    SCAN_SUBNET_PART_NETMASK,
    SCAN_SUBNET_PART_NETWORK_ADDRESS,
    SetupScanSubnetInput,
    split_scan_subnet_suggestions,
)

CONF_SCAN_AUTOMATICALLY = "scan_automatically"
CONF_SCAN_SUBNET_MODE = "scan_subnet_mode"
CONF_SCAN_NETWORK_ADDRESS = "scan_network_address"
CONF_SCAN_NETMASK = "scan_netmask"
CONF_SCAN_CIDR = "scan_cidr"
CONF_SETUP_MODE = "setup_mode"
SETUP_SCAN_PROGRESS_ACTION = "scan_dhe"


def apply_validation_error(errors: dict[str, str], err: ValueError) -> None:
    """Map validation exceptions to visible config-flow fields."""
    code = str(err) or "invalid_host"
    if code == "invalid_port":
        errors[CONF_PORT] = code
    elif code == "invalid_internal_scald_protection":
        errors[CONF_INTERNAL_SCALD_PROTECTION] = code
    elif code == "embedded_port_not_supported":
        errors[CONF_HOST] = code
    else:
        errors[CONF_HOST] = "invalid_host"


def scan_subnet_network_mask_input(
    user_input: dict[str, Any],
) -> SetupScanSubnetInput:
    """Return normalized network-address and subnet-mask input."""
    return SetupScanSubnetInput(
        network_address=str(user_input.get(CONF_SCAN_NETWORK_ADDRESS) or "").strip(),
        netmask=str(user_input.get(CONF_SCAN_NETMASK) or "").strip(),
    )


def scan_subnet_cidr_input(user_input: dict[str, Any]) -> SetupScanSubnetInput:
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
        raise ValueError("invalid_scan_subnet")
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
