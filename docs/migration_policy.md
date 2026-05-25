# Migration Policy (v2 line)

This document defines migration expectations for the v2 release line.

## Current Policy

- The v2 beta/hardening line prioritizes clean runtime behavior over broad
  compatibility shims for old private/dev snapshots.
- No silent data rewrites for unknown legacy states.
- No automatic token or config storage rewrites without explicit migration
  design and tests.

## When Upgrades Fail From Old Private/Dev States

Recommended recovery path:

1. Reload the integration once.
2. Run `Repair pairing` if token/pairing is invalid.
3. If state remains inconsistent, remove and re-add the integration cleanly.

## Public Stability Guarantees

- Existing public entity IDs should stay stable across normal supported
  upgrades.
- Existing config entry behavior should stay stable unless explicitly called out
  in release notes.

## Change Control For Future Migrations

Before adding any migration logic:

- Add deterministic tests for old and new data shapes.
- Document trigger conditions and rollback behavior.
- Document privacy impact (if storage fields are transformed).
