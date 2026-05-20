"""Quality-scale guardrails for Home Assistant integration structure."""

from __future__ import annotations

import importlib
import re
from pathlib import Path

from custom_components.stiebel_dhe_connect.const import DOMAIN, PLATFORMS


ROOT = Path(__file__).resolve().parents[1]
QUALITY_SCALE = ROOT / "custom_components" / DOMAIN / "quality_scale.yaml"
SILVER_RULES = {
    # Bronze
    "action-setup",
    "appropriate-polling",
    "brands",
    "common-modules",
    "config-flow-test-coverage",
    "config-flow",
    "dependency-transparency",
    "docs-actions",
    "docs-high-level-description",
    "docs-installation-instructions",
    "docs-removal-instructions",
    "entity-unique-id",
    "has-entity-name",
    "runtime-data",
    "test-before-configure",
    "test-before-setup",
    "unique-config-entry",
    # Silver
    "action-exceptions",
    "config-entry-unloading",
    "docs-configuration-parameters",
    "docs-installation-parameters",
    "entity-unavailable",
    "integration-owner",
    "log-when-unavailable",
    "parallel-updates",
    "reauthentication-flow",
    "test-coverage",
}


def _done_rules(text: str) -> set[str]:
    done: set[str] = set()
    current_rule: str | None = None
    for line in text.splitlines():
        rule_match = re.match(r"^  ([a-z0-9-]+):(?:\s*(done|todo))?\s*$", line)
        if rule_match:
            current_rule = rule_match.group(1)
            if rule_match.group(2) == "done":
                done.add(current_rule)
            continue
        status_match = re.match(r"^    status:\s*(done|todo|exempt)\s*$", line)
        if status_match and current_rule and status_match.group(1) == "done":
            done.add(current_rule)
    return done


def test_platforms_define_parallel_updates() -> None:
    """Keep platform update concurrency explicit for Home Assistant."""
    for platform in PLATFORMS:
        module = importlib.import_module(f"custom_components.{DOMAIN}.{platform.value}")
        assert getattr(module, "PARALLEL_UPDATES", None) == 0


def test_quality_scale_tracks_silver_rules() -> None:
    """Keep Home Assistant Silver rule tracking explicit in the integration."""
    text = QUALITY_SCALE.read_text(encoding="utf-8")
    assert sorted(SILVER_RULES - _done_rules(text)) == []
