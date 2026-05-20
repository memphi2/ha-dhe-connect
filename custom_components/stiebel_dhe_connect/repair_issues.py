"""Home Assistant Repairs issue helpers for DHE Connect."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DEFAULT_NAME, DOMAIN

PAIRING_REQUIRED_ISSUE = "pairing_required"


def pairing_required_issue_id(entry_id: str) -> str:
    """Return the stable Repairs issue ID for a DHE config entry."""
    return f"{PAIRING_REQUIRED_ISSUE}_{entry_id}"


@callback
def async_create_pairing_issue(
    hass: HomeAssistant,
    entry_id: str,
    name: str | None,
) -> None:
    """Create a fixable issue when the stored DHE token is no longer accepted."""
    if _entry_is_connected(hass, entry_id):
        async_delete_pairing_issue(hass, entry_id)
        return

    ir.async_create_issue(
        hass=hass,
        domain=DOMAIN,
        issue_id=pairing_required_issue_id(entry_id),
        is_fixable=True,
        is_persistent=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key=PAIRING_REQUIRED_ISSUE,
        translation_placeholders={"name": name or DEFAULT_NAME},
        data={"entry_id": entry_id},
    )


@callback
def async_delete_pairing_issue(hass: HomeAssistant, entry_id: str) -> None:
    """Delete a pairing issue after the entry authenticates again."""
    ir.async_delete_issue(
        hass=hass,
        domain=DOMAIN,
        issue_id=pairing_required_issue_id(entry_id),
    )


def _entry_is_connected(hass: HomeAssistant, entry_id: str) -> bool:
    """Return True when the loaded runtime already authenticated successfully."""
    entry = hass.config_entries.async_get_entry(entry_id)
    runtime = getattr(entry, "runtime_data", None) if entry is not None else None
    client = getattr(runtime, "client", None)
    diagnostic_state = getattr(client, "diagnostic_state", None)
    if not isinstance(diagnostic_state, dict):
        return False
    return diagnostic_state.get("connection_state") == "connected"
