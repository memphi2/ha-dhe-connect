"""Repairs flow for DHE Connect."""

from __future__ import annotations

from typing import cast

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_HOST, CONF_PORT

from . import config_flow
from .config_entry_helpers import entry_target
from .const import DOMAIN
from .config_flow_discovery import coerce_setup_pairing_result as _coerce_setup_pairing_result
from .repair_issues import (
    PAIRING_REQUIRED_ISSUE,
    TOKEN_INVALID_ISSUE,
    async_delete_repair_issues,
    repair_issue_id,
)
from .token_file_helpers import token_file_for_target

_PAIRING_FIX_FLOW_ISSUES = frozenset(
    {
        PAIRING_REQUIRED_ISSUE,
        TOKEN_INVALID_ISSUE,
    }
)


class PairingRequiredRepairFlow(RepairsFlow):
    """Repair a DHE entry by requesting and validating a fresh local token."""

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__()
        self._entry = entry

    async def async_step_init(
        self,
        user_input: dict[str, str] | None = None,
    ) -> data_entry_flow.FlowResult:
        """Start the repair confirmation step."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self,
        user_input: dict[str, str] | None = None,
    ) -> data_entry_flow.FlowResult:
        """Request pairing and validate the new token when submitted."""
        target = entry_target(self._entry)
        if target is None:
            return self.async_abort(reason="invalid_entry")

        errors: dict[str, str] = {}
        host, port = target
        if user_input is not None:
            if not await config_flow._can_connect(self.hass, host, port):
                errors["base"] = "cannot_connect"
            else:
                pairing_result = _coerce_setup_pairing_result(
                    await config_flow._validate_setup_pairing(
                        self.hass,
                        host,
                        port,
                        token_file_for_target(host, port),
                    )
                )
                if pairing_result.error_key is None:
                    async_delete_repair_issues(self.hass, self._entry.entry_id)
                    if self._entry.state in (
                        ConfigEntryState.LOADED,
                        ConfigEntryState.SETUP_RETRY,
                    ):
                        await self.hass.config_entries.async_reload(
                            self._entry.entry_id
                        )
                    return self.async_create_entry(data={})
                errors["base"] = pairing_result.error_key

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={
                CONF_HOST: host,
                CONF_PORT: str(port),
                "name": self._entry.title,
            },
        )


class MissingEntryRepairFlow(RepairsFlow):
    """Abort stale repair issues whose config entry no longer exists."""

    async def async_step_init(
        self,
        user_input: dict[str, str] | None = None,
    ) -> data_entry_flow.FlowResult:
        """Abort stale repair issue."""
        del user_input
        return self.async_abort(reason="entry_not_found")


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create a Repairs flow for a DHE issue."""
    issue_type = _pairing_fix_issue_type(issue_id)
    if issue_type is None:
        raise ValueError(f"unknown repair {issue_id}")

    raw_entry_id = data.get("entry_id") if data else None
    entry_id = str(raw_entry_id or issue_id.removeprefix(f"{issue_type}_"))
    if issue_id != repair_issue_id(issue_type, entry_id):
        raise ValueError(f"repair issue does not match entry {entry_id}")

    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        return MissingEntryRepairFlow()
    return PairingRequiredRepairFlow(cast(ConfigEntry, entry))


def _pairing_fix_issue_type(issue_id: str) -> str | None:
    """Return the supported fix-flow issue type for one issue id."""
    for issue_type in _PAIRING_FIX_FLOW_ISSUES:
        if issue_id.startswith(f"{issue_type}_"):
            return issue_type
    return None
