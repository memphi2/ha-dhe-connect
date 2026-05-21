# Platinum Preparation (v1.8.0 branch)

This document tracks the remaining work to move this custom integration from a
Gold-core-oriented release line toward Home Assistant Quality Scale Platinum
readiness.

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
- `strict-typing`: `todo`

So the only active Platinum gap in this repository is strict typing depth.

## Strict-Typing Work Plan

1. Tighten mypy profile incrementally:
   - Done on `v1.8.0`: `warn_return_any = true`
   - Done on `v1.8.0`: `warn_unused_ignores = true`
   - Done on `v1.8.0` for first module set:
     `async_helpers`, `connection_helpers`, `connection_probe`,
     `diagnostics`, `pairing_validation`
   - Expanded on `v1.8.0`: `config_flow`, `switch`
   - Next: expand `disallow_untyped_defs = true` to additional runtime/platform
     module groups
2. Resolve runtime mixin `self` contracts with explicit Protocols:
   - command context
   - runtime parser context
   - transport/auth context
3. Keep module-by-module gates:
   - promote one module group at a time
   - keep CI green at each step
4. Avoid broad `# type: ignore` growth:
   - each new ignore requires a short rationale comment
5. Extend typing tests for high-risk runtime paths:
   - reconnect + retry
   - pairing/reauth + repairs
   - discovery update paths

## Progress Snapshot

- Current typing gate stays green with `warn_return_any` and
  `warn_unused_ignores` enabled.
- `disallow_untyped_defs` is now enforced for a first low-risk module group.
- No runtime behavior changes were introduced for this typing hardening step.

## Recommended Validation Gate For Each Typing Round

```bash
python scripts/check_typing.py
python -m ruff check custom_components/stiebel_dhe_connect tests scripts
python scripts/check_integration.py
python scripts/check_coverage.py
```

Optional release-style gate:

```bash
python scripts/release_check.py --run-local-checks --expect-tag skip --expect-github-release skip
```

## Done Criteria For Platinum-Prep Milestone

- `strict-typing` can be switched from `todo` to `done` in `quality_scale.yaml`
- typing gate remains green without relaxing mypy scope
- no regressions in Repairs, Reconfigure, Discovery or diagnostics tests
