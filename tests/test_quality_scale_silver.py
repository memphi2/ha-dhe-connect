"""Quality-scale guardrails for Home Assistant integration structure."""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import yaml

from custom_components.stiebel_dhe_connect.const import DOMAIN, PLATFORMS


ROOT = Path(__file__).resolve().parents[1]
QUALITY_SCALE = ROOT / "custom_components" / DOMAIN / "quality_scale.yaml"
BRONZE_RULES = {
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
}
BRONZE_EVIDENCE_RULES = BRONZE_RULES | {"entity-event-setup"}
SILVER_ONLY_RULES = {
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
SILVER_RULES = BRONZE_RULES | SILVER_ONLY_RULES
GOLD_CORE_RULES = {
    "reconfiguration-flow",
    "repair-issues",
}
GOLD_EVIDENCE_RULES = {
    "devices",
    "diagnostics",
    "discovery-update-info",
    "discovery",
    "docs-data-update",
    "docs-examples",
    "docs-known-limitations",
    "docs-supported-devices",
    "docs-supported-functions",
    "docs-troubleshooting",
    "docs-use-cases",
    "dynamic-devices",
    "entity-category",
    "entity-device-class",
    "entity-disabled-by-default",
    "entity-translations",
    "exception-translations",
    "icon-translations",
    "reconfiguration-flow",
    "repair-issues",
    "stale-devices",
}
PLATINUM_RULES = {
    "async-dependency",
    "inject-websession",
    "strict-typing",
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


def test_quality_scale_tracks_silver_and_gold_core_rules() -> None:
    """Keep Home Assistant Silver and Gold-core rule tracking explicit."""
    text = QUALITY_SCALE.read_text(encoding="utf-8")
    assert sorted((SILVER_RULES | GOLD_CORE_RULES) - _done_rules(text)) == []


def test_quality_scale_tracks_platinum_rules_as_done_or_exempt() -> None:
    """Keep local Platinum-oriented evidence from drifting back to todo."""
    data = yaml.safe_load(QUALITY_SCALE.read_text(encoding="utf-8"))
    rules = data["rules"]
    for rule in PLATINUM_RULES:
        value = rules[rule]
        status = value if isinstance(value, str) else value["status"]
        assert status in {"done", "exempt"}, rule


def test_quality_scale_evidence_maps_rules_to_tests_and_docs() -> None:
    """Keep the rule evidence table explicit for review and release work."""
    data = yaml.safe_load(QUALITY_SCALE.read_text(encoding="utf-8"))
    evidence = data["evidence"]

    assert set(evidence["silver"]) == SILVER_ONLY_RULES
    assert set(evidence["bronze"]) == BRONZE_EVIDENCE_RULES
    assert set(evidence["gold"]) == GOLD_EVIDENCE_RULES

    for group in ("silver", "bronze", "gold"):
        for rule, mapping in evidence[group].items():
            assert set(mapping) == {"implementation", "tests", "docs"}, rule
            assert mapping["implementation"].strip(), rule
            assert mapping["tests"].strip(), rule
            assert mapping["docs"].strip(), rule
