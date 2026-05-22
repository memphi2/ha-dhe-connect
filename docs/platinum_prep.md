# Platinum Preparation (v1.8.1 branch)

This document tracks the hardening work used to move this custom integration
from a Gold-track baseline toward Home Assistant Quality Scale
Platinum readiness.

It does not claim official Home Assistant Core certification.

## Scope

- No protocol behavior changes
- No entity ID or unique ID changes
- No token-file format migration
- No new DHE feature surface

## Current Platinum Status

`custom_components/stiebel_dhe_connect/quality_scale.yaml` currently keeps:

- `async-dependency`: `exempt`
- `inject-websession`: `exempt`
- `strict-typing`: `done`

So the repository has no active Platinum-rule gap in the local evidence file.
This remains a custom-integration quality target and is not an official Home
Assistant Core certification.

## Strict-Typing Evidence

The strict-typing path was tightened incrementally so each step stayed
reviewable:

1. Enabled strict mypy flags:
   - Done on `v1.8.0`: `warn_return_any = true`
   - Done on `v1.8.0`: `warn_unused_ignores = true`
   - Done on `v1.8.0`: `disallow_untyped_defs = true` globally for the typed
     integration module set
   - Done on `v1.8.0`: `check_untyped_defs = true`
   - Done on `v1.8.0`: `no_implicit_optional = true`
   - Done on `v1.8.0`: `strict_equality = true`
   - Done on `v1.8.0`: `warn_redundant_casts = true`
   - Done on `v1.8.0`: `warn_unreachable = true`
   - Done on `v1.8.0`: `disallow_any_generics = true`
   - Done on `v1.8.0`: `disallow_incomplete_defs = true`
   - Done on `v1.8.0`: `disallow_untyped_calls = true`
   - Done on `v1.8.0`: `extra_checks = true`
   - Done on `v1.8.0`: `warn_unused_configs = true`
   - Done on `v1.8.0`: `follow_imports = "normal"`
   - Done on `v1.8.0`: `python_version = "3.14"` to match the repository CI
     runtime and parse current Home Assistant dependency syntax consistently
   - Done on `v1.8.0`: `strict = true`
   - Done on `v1.8.0`: removed broad `ignore_missing_imports`
2. Kept the gate scoped to every top-level integration module.
3. Added a direct guard in `scripts/check_typing.py` so new integration modules
   cannot be accidentally left out of mypy.
4. Removed HA typing mismatches found by normal import following without
   changing DHE protocol behavior.
5. Added explicit Protocol contracts for the mixin surfaces:
   `DHEClientCommandContext`, `DHEClientTransportContext`,
   `DHEClientRuntimeContext`, `DHEClientConnectionContext` and
   `DHEClientDiagnosticsContext`.
6. Added type-only structural assertions so mypy verifies the concrete
   `DHEClient` still satisfies those mixin contracts.

## Progress Snapshot

- Current typing gate stays green with return-value, unused-ignore,
  redundant-cast, unreachable-code, strict-equality, no-untyped-generics,
  no-untyped-calls, no-incomplete-defs, extra-checks and implicit-optional
  checks enabled.
- The active mypy profile now uses `strict = true`, follows imports normally,
  and targets Python 3.14 to match the GitHub Actions validation runtime.
- The gate no longer uses broad missing-import suppression.
- `disallow_untyped_defs` is now enforced globally for the typed module set.
- `scripts/check_typing.py` now fails before mypy if a top-level integration
  module is missing from `tool.mypy.files` or if the gate references a stale
  integration path.
- No runtime behavior changes were introduced for this typing hardening step.
- Runtime/parser hardening now has deterministic guards for malformed runtime
  payloads, reconnect during commands, delayed readbacks, duplicate discovery
  conflicts, reconnect-grace repairs, token-invalid runtime failures,
  reconfigure during reconnect grace, and unknown radio/weather payload shapes.

## Runtime, Recorder And Diagnostics Architecture

- Runtime updates are push based. The shared client owns the Socket.IO /
  Engine.IO session and platforms subscribe through callbacks instead of
  polling device state independently.
- Platform modules set `PARALLEL_UPDATES = 0` because no entity performs its
  own parallel device I/O. Commands are serialized by the client command lock
  and readback futures.
- Reconnect behavior is handled by `DHEConnectionSupervisor`: exponential
  backoff, reconnect grace and explicit diagnostic state avoid transient
  offline noise while still marking entities unavailable after the grace window.
- High-frequency values use scoped state dedupe and default-disabled
  diagnostics where appropriate. Timer and runtime-detail entities that can
  change frequently are kept out of long-term-statistics shapes unless Home
  Assistant has a matching semantic class.
- Internal entity read paths avoid full snapshotting of runtime attributes:
  sensor, binary-sensor and text entities read from the client's internal
  measurement-attribute cache map in update-critical paths to reduce per-update
  allocations.
- Sensor entities were optimized to avoid always cloning recorder attributes:
  recorded attribute dictionaries are snapshot only if value/state thresholds
  indicate a state write is likely, which keeps high-frequency updates lighter
  under bursty runtime streams.
- Static sensor descriptions, options-flow handling and Home Assistant service
  registration are split into dedicated modules. The runtime-facing modules stay
  smaller while preserving existing entity IDs, service names and config-entry
  behavior.
- Repeated weather, radio, consumption and saving-monitor payloads are kept as
  bounded summaries or attributes only when needed for services, options flows
  or visible entity state. Stable internal ODB values are recognized and
  ignored at normal log levels.
- Support diagnostics export counts, key lists and summarized parser/reconnect
  state. Raw token values, token paths, private hosts, local URLs, IP
  addresses, MAC addresses, session IDs, WebSocket URLs and raw WebSocket
  payloads are redacted or reduced to presence flags.
- v1.8.1 extends that redaction to raw IPv6 strings and keeps pairing
  notification identifiers scoped without embedding raw host or port details.
- Stable hashed identifiers are not emitted today. If they are added later,
  they must be opt-in and must not be reversible to private host, MAC, token or
  product identifiers.
- Coverage is strict for deterministic modules. HA setup/platform glue and
  live transport orchestration are deliberately excluded from the 95% line
  metric when their behavior is better covered by HA fixture tests, Fake-DHE
  tests, release checks and optional live smoke gates.
- CI runs a repository-owned deprecation guard. It rejects deprecated Python
  APIs and warning-suppression settings in owned Python, workflow, README,
  changelog and documentation files; current third-party dependency warnings
  are left visible and must be resolved by dependency upgrades or upstream
  fixes.
- The GitHub pytest annotation plugin is disabled. This does not filter pytest
  warnings from logs; it prevents external dependency deprecations from being
  duplicated as repository annotations.
- Mounted HA smoke can emit sanitized JSON evidence with `--evidence-json`.
  That artifact keeps pass/fail checks, entity counts, monitor settings and
  recorder top writers without storing local paths, hosts, IPs, token paths or
  credentials.

## Recommended Validation Gate For Each Typing Round

```bash
python scripts/check_typing.py
python scripts/check_deprecations.py
python -m ruff check custom_components/stiebel_dhe_connect tests scripts
python scripts/check_integration.py
python scripts/check_coverage.py
```

Optional release-style gate:

```bash
python scripts/release_check.py --run-local-checks --expect-tag skip --expect-github-release skip
```

## Done Criteria For Platinum-Prep Milestone

- `strict-typing` is switched from `todo` to `done` in `quality_scale.yaml`.
- Typing gate remains green without relaxing mypy scope.
- No regressions in Repairs, Reconfigure, Discovery or diagnostics tests.
- Runtime performance remains bounded by design:
  - Setup scan is capped by `DHE_SCAN_MAX_HOSTS` and bounded by `scan_concurrency_for_host_count()`.
  - Runtime parser high-frequency paths avoid unnecessary type-branch work in repeated message loops.
  - Runtime-category counters and invalid-read diagnostics skip repeated defensive runtime checks in steady-state paths.
  - Recorder writes stay event-driven and state-delta based; derived/wide payload entities stay attribute-light unless state changes.
