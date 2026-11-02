# Platinum Preparation Notes

This document keeps the engineering rationale for the Platinum-track setup of
this custom integration.

It does not claim official Home Assistant Core certification.

## Quality Inventory

Open rules: none

The local inventory tracks all 54 rules in the
[official rule list](https://contributors.home-assistant.io/core/quality-scale/rules/),
checked on 2026-11-02. `scripts/check_quality_scale.py` parses YAML, rejects
duplicate/missing/unknown rules and invalid statuses, requires a reason for
every exemption or TODO and checks implementation/test/documentation evidence
for every rule. The integration guard runs it in CI without network access.
Revisit this snapshot when adopting a new HA baseline; it is not an upstream
rule-change detector.

There are no custom trigger or condition platforms, so `docs-triggers` and
`docs-conditions` are exempt. Standard entity-state/numeric-state automation
examples are in [examples.md](examples.md). `async-dependency` and
`inject-websession` remain exempt because the async protocol client is owned
by the integration, not an external dependency accepting a session.

If a rule becomes `todo`, record its reason in the YAML and list its rule ID in
the `Open rules:` line above. Required done rules cannot be silently downgraded.
Evidence descriptions still require human review; the guard checks consistency,
not fulfillment of Home Assistant's official review process.

## Scope

- No protocol-semantic changes for hardening-only rounds
- No entity ID / unique ID churn
- No token format churn without explicit migration design
- No private data in diagnostics or release artifacts

## Architecture Principles

1. Runtime over polling
   - Shared long-lived client session
   - Platform entities subscribe via callbacks
   - `PARALLEL_UPDATES = 0` for entity platforms

2. Recorder hygiene
   - High-churn diagnostics disabled by default where possible
   - State writes deduped on meaningful changes
   - Attribute payloads kept compact

3. Diagnostics hygiene
   - Redact host/IP/MAC/token/session values
   - Export summary/state counters instead of raw payload dumps

4. Test strategy
   - Deterministic parser/runtime tests
   - HA fixture tests for setup/reload/unload/flows
   - Fake-DHE transport/runtime tests for reconnect/pairing edge cases
   - Optional live smoke gates for real-network verification

5. Typing strategy
   - Strict mypy profile for integration modules
   - Explicit Protocol contracts across client mixins
   - Minimize `Any`, broad casts and unmanaged ignores

## Validation Gate

Use the maintained command set in [validation.md](validation.md), including
coverage, HA baseline provenance, privacy/deprecation guards, strict typing and
Ruff. Do not maintain a reduced duplicate checklist here.

The loopback runtime soak is a bounded regression test, not proof of multi-day
device stability. Real-device evidence belongs in [firmware_matrix.md](firmware_matrix.md).
Live smoke checks require a deliberately authorized test installation.

For publication, follow [release_process.md](release_process.md). Skipping tag
or release checks during development is not a stable-release approval.

## Exit Criteria For Platinum-Track Rounds

- Quality-scale evidence remains consistent in `quality_scale.yaml`
- Validation gate stays green without relaxing checks
- No new privacy regressions in docs/logging/diagnostics
- No runtime/connectivity regressions in fixture and Fake-DHE tests
