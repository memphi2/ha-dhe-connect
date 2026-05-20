"""Setup-scan state helpers for the DHE config flow."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from ipaddress import IPv4Network
from typing import Any

from homeassistant.core import HomeAssistant

from .config_entry_helpers import is_target_used_by_other_entry
from .config_flow_setup import language_from_hass
from .const import DEFAULT_PORT
from .setup_scan import DHEHostCandidate, candidate_defaults, setup_scan_status_text


@dataclass
class SetupScanState:
    """Track one optional setup scan while keeping config-flow code focused."""

    task: asyncio.Task[list[DHEHostCandidate]] | None = None
    candidates: list[DHEHostCandidate] = field(default_factory=list)
    done: bool = False
    failed: bool = False
    networks: list[IPv4Network] | None = None
    port: int = DEFAULT_PORT

    def available_candidates(self, hass: HomeAssistant) -> list[DHEHostCandidate]:
        """Return scan candidates that are not already configured."""
        return [
            candidate
            for candidate in self.candidates
            if not is_target_used_by_other_entry(hass, candidate.host, candidate.port)
        ]

    def user_defaults(self, hass: HomeAssistant) -> dict[str, Any]:
        """Return manual-form defaults derived from scan candidates."""
        available = self.available_candidates(hass)
        if not available:
            return {}
        return candidate_defaults(available[0])

    def description_placeholders(self, hass: HomeAssistant) -> dict[str, str]:
        """Return manual-form placeholders that describe scan status."""
        available = self.available_candidates(hass)
        return {
            "scan_status": setup_scan_status_text(
                language_from_hass(hass),
                scanned=self.done,
                found=len(self.candidates),
                available=len(available),
                failed=self.failed,
            )
        }

    def cancel(self) -> None:
        """Cancel an unfinished scan task."""
        if self.task is not None and not self.task.done():
            self.task.cancel()
        self.task = None
