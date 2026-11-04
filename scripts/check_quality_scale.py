"""Validate the complete local quality inventory, not an official HA tier."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
QUALITY_PATH = Path("custom_components/stiebel_dhe_connect/quality_scale.yaml")
DOC_PATH = Path("docs/platinum_prep.md")
# Snapshot checked against the official rules on 2026-11-02; CI stays offline.
RULE_GROUPS = {
    "bronze": frozenset({
        "action-setup", "appropriate-polling", "brands", "common-modules",
        "config-flow-test-coverage", "config-flow", "dependency-transparency",
        "docs-actions", "docs-conditions", "docs-high-level-description",
        "docs-installation-instructions", "docs-removal-instructions", "docs-triggers",
        "entity-event-setup", "entity-unique-id", "has-entity-name", "runtime-data",
        "test-before-configure", "test-before-setup", "unique-config-entry",
    }),
    "silver": frozenset({
        "action-exceptions", "config-entry-unloading", "docs-configuration-parameters",
        "docs-installation-parameters", "entity-unavailable", "integration-owner",
        "log-when-unavailable", "parallel-updates", "reauthentication-flow", "test-coverage",
    }),
    "gold": frozenset({
        "devices", "diagnostics", "discovery-update-info", "discovery", "docs-data-update",
        "docs-examples", "docs-known-limitations", "docs-supported-devices",
        "docs-supported-functions", "docs-troubleshooting", "docs-use-cases",
        "dynamic-devices", "entity-category", "entity-device-class",
        "entity-disabled-by-default", "entity-translations", "exception-translations",
        "icon-translations", "reconfiguration-flow", "repair-issues", "stale-devices",
    }),
    "platinum": frozenset({"async-dependency", "inject-websession", "strict-typing"}),
}
ALL_RULES = frozenset().union(*RULE_GROUPS.values())
REQUIRED_DONE = (
    RULE_GROUPS["bronze"] - {"docs-conditions", "docs-triggers", "entity-event-setup"}
    | RULE_GROUPS["silver"] | {"reconfiguration-flow", "repair-issues", "strict-typing"}
)


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate keys instead of silently replacing earlier evidence."""

    def construct_mapping(self, node, deep=False):
        keys = [self.construct_object(key, deep=deep) for key, _ in node.value]
        try:
            if len(keys) != len(set(keys)):
                raise ValueError("duplicate YAML mapping key")
        except TypeError:
            raise ValueError("YAML mapping keys must be scalar") from None
        return super().construct_mapping(node, deep=deep)


def validate_quality_scale(text: str, docs: str) -> list[str]:
    """Reject inventory, status, evidence and documentation drift."""
    try:
        data = yaml.load(text, Loader=UniqueKeyLoader)
    except (yaml.YAMLError, ValueError):
        return ["quality_scale.yaml is invalid or has duplicate keys"]
    if not isinstance(data, dict) or set(data) != {"rules", "evidence"}:
        return ["quality_scale.yaml must contain rules and evidence mappings"]
    rules, evidence = data["rules"], data["evidence"]
    if not isinstance(rules, dict) or not isinstance(evidence, dict):
        return ["quality_scale.yaml rules and evidence must be mappings"]
    failures: list[str] = []
    if set(rules) != ALL_RULES:
        failures.append("quality_scale.yaml has missing or unknown rules")
    if set(evidence) != set(RULE_GROUPS):
        failures.append("quality_scale.yaml has missing or unknown evidence groups")
    open_rules: set[str] = set()
    for rule in sorted(ALL_RULES & rules.keys()):
        value = rules[rule]
        if isinstance(value, dict):
            status, comment = value.get("status"), value.get("comment")
            if set(value) - {"status", "comment"}:
                failures.append(f"{rule}: unknown rule fields")
        else:
            status, comment = value, None
        if not isinstance(status, str) or status not in {"done", "todo", "exempt"}:
            failures.append(f"{rule}: invalid status")
            continue
        if status in {"todo", "exempt"} and (not isinstance(comment, str) or not comment.strip()):
            failures.append(f"{rule}: {status} requires a reason")
        if rule in REQUIRED_DONE and status != "done":
            failures.append(f"{rule}: required done rule regressed")
        if status == "todo":
            open_rules.add(rule)
    for group, expected in RULE_GROUPS.items():
        entries = evidence.get(group)
        if not isinstance(entries, dict) or set(entries) != expected:
            failures.append(f"{group}: evidence inventory does not match rules")
            continue
        for rule, mapping in entries.items():
            if (
                not isinstance(mapping, dict)
                or set(mapping) != {"implementation", "tests", "docs"}
                or any(not isinstance(value, str) or not value.strip() for value in mapping.values())
            ):
                failures.append(f"{rule}: incomplete implementation/tests/docs evidence")
    summary = ", ".join(f"`{rule}`" for rule in sorted(open_rules)) or "none"
    if f"Open rules: {summary}" not in docs.splitlines():
        failures.append(f"docs/platinum_prep.md must state Open rules: {summary}")
    if "It does not claim official Home Assistant Core certification." not in docs:
        failures.append("quality documentation must retain the unofficial scope statement")
    return failures


def check_files(root: Path = ROOT) -> list[str]:
    try:
        return validate_quality_scale(
            (root / QUALITY_PATH).read_text(encoding="utf-8"),
            (root / DOC_PATH).read_text(encoding="utf-8"),
        )
    except OSError:
        return ["missing or unreadable quality inventory/documentation"]


def main() -> int:
    failures = check_files()
    for failure in failures:
        print(f"ERROR: {failure}", file=sys.stderr)
    if not failures:
        print(f"quality-scale inventory ok ({len(ALL_RULES)} rules)")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
