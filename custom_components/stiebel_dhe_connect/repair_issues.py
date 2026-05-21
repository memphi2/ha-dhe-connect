"""Home Assistant Repairs issue helpers for DHE Connect."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DEFAULT_NAME, DOMAIN

PAIRING_REQUIRED_ISSUE = "pairing_required"
TOKEN_INVALID_ISSUE = "token_invalid"
DEVICE_UNREACHABLE_ISSUE = "device_unreachable"
DISCOVERY_CONFLICT_ISSUE = "discovery_conflict"
HOST_CHANGED_OR_UNREACHABLE_ISSUE = "host_changed_or_unreachable"

FIXABLE_REPAIR_ISSUES = frozenset(
    {
        PAIRING_REQUIRED_ISSUE,
        TOKEN_INVALID_ISSUE,
    }
)
ALL_REPAIR_ISSUES = frozenset(
    {
        PAIRING_REQUIRED_ISSUE,
        TOKEN_INVALID_ISSUE,
        DEVICE_UNREACHABLE_ISSUE,
        DISCOVERY_CONFLICT_ISSUE,
        HOST_CHANGED_OR_UNREACHABLE_ISSUE,
    }
)


def repair_issue_id(issue_type: str, entry_id: str) -> str:
    """Return the stable Repairs issue ID for one config entry + issue type."""
    return f"{issue_type}_{entry_id}"


def pairing_required_issue_id(entry_id: str) -> str:
    """Backward-compatible accessor for the pairing-required issue id."""
    return repair_issue_id(PAIRING_REQUIRED_ISSUE, entry_id)


def token_invalid_issue_id(entry_id: str) -> str:
    """Return the token-invalid issue ID for one DHE config entry."""
    return repair_issue_id(TOKEN_INVALID_ISSUE, entry_id)


def device_unreachable_issue_id(entry_id: str) -> str:
    """Return the device-unreachable issue ID for one DHE config entry."""
    return repair_issue_id(DEVICE_UNREACHABLE_ISSUE, entry_id)


def discovery_conflict_issue_id(entry_id: str) -> str:
    """Return the discovery-conflict issue ID for one DHE config entry."""
    return repair_issue_id(DISCOVERY_CONFLICT_ISSUE, entry_id)


def host_changed_or_unreachable_issue_id(entry_id: str) -> str:
    """Return the host-changed-or-unreachable issue ID for one config entry."""
    return repair_issue_id(HOST_CHANGED_OR_UNREACHABLE_ISSUE, entry_id)


@callback
def async_create_repair_issue(
    hass: HomeAssistant,
    entry_id: str,
    issue_type: str,
    name: str | None,
    placeholders: Mapping[str, Any] | None = None,
) -> None:
    """Create one DHE Repairs issue."""
    if issue_type not in ALL_REPAIR_ISSUES:
        raise ValueError(f"unknown repair issue type: {issue_type}")

    if _entry_is_connected(hass, entry_id):
        async_delete_repair_issues(hass, entry_id)
        return

    translation_placeholders = {"name": name or DEFAULT_NAME}
    if placeholders:
        translation_placeholders.update(
            {
                str(key): str(value)
                for key, value in placeholders.items()
                if value is not None
            }
        )

    ir.async_create_issue(
        hass=hass,
        domain=DOMAIN,
        issue_id=repair_issue_id(issue_type, entry_id),
        is_fixable=issue_type in FIXABLE_REPAIR_ISSUES,
        is_persistent=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key=issue_type,
        translation_placeholders=translation_placeholders,
        data={"entry_id": entry_id, "issue_type": issue_type},
    )


@callback
def async_delete_repair_issue(
    hass: HomeAssistant,
    entry_id: str,
    issue_type: str,
) -> None:
    """Delete one DHE Repairs issue."""
    if issue_type not in ALL_REPAIR_ISSUES:
        return
    ir.async_delete_issue(hass=hass, domain=DOMAIN, issue_id=repair_issue_id(issue_type, entry_id))


@callback
def async_delete_repair_issues(
    hass: HomeAssistant,
    entry_id: str,
    *,
    keep_types: Iterable[str] = (),
) -> None:
    """Delete all DHE Repairs issues for one entry except optional keep list."""
    keep = {issue_type for issue_type in keep_types if issue_type in ALL_REPAIR_ISSUES}
    for issue_type in ALL_REPAIR_ISSUES:
        if issue_type in keep:
            continue
        async_delete_repair_issue(hass, entry_id, issue_type)


@callback
def async_create_pairing_issue(
    hass: HomeAssistant,
    entry_id: str,
    name: str | None,
    placeholders: Mapping[str, Any] | None = None,
) -> None:
    """Backward-compatible pairing-required issue creation wrapper."""
    async_create_repair_issue(
        hass,
        entry_id,
        PAIRING_REQUIRED_ISSUE,
        name,
        placeholders=placeholders,
    )


@callback
def async_delete_pairing_issue(hass: HomeAssistant, entry_id: str) -> None:
    """Backward-compatible pairing-required issue deletion wrapper."""
    async_delete_repair_issue(hass, entry_id, PAIRING_REQUIRED_ISSUE)


def _entry_is_connected(hass: HomeAssistant, entry_id: str) -> bool:
    """Return True when the loaded runtime already authenticated successfully."""
    entry = hass.config_entries.async_get_entry(entry_id)
    runtime = getattr(entry, "runtime_data", None) if entry is not None else None
    client = getattr(runtime, "client", None)
    diagnostic_state = getattr(client, "diagnostic_state", None)
    if not isinstance(diagnostic_state, dict):
        return False
    return diagnostic_state.get("connection_state") == "connected"
