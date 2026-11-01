# Migration Policy (v2 line)

This document defines migration expectations for the v2 release line.

## Current Policy

- Installation and updates use the [catalog workflow](installation.md).
  The domain remains `stiebel_dhe_connect`; existing HACS installations do not
  need a new config entry for the display-name or catalog change.
- This line supports Home Assistant `2026.10.4` and newer, with a narrow adapter
  for the 2026.10/2026.11 API differences. Older HA installations need a release
  with a matching minimum; `v2.0.9` requires HA `2026.10.1` or newer.
- The v2 hardening line prioritizes clean runtime behavior over broad
  compatibility shims for old private/dev snapshots.
- No silent data rewrites for unknown legacy states.
- No automatic token or config storage rewrites without explicit migration
  design and tests.
- Since v2.0.7, setup and retargeting explicitly migrate well-formed per-target
  host/port token files into config-entry data, then remove the candidate files.
  Existing config-entry tokens take precedence; retargeting prefers the new
  target's file over the old target's file. Entry-ID-based and shared files from
  private/dev snapshots are not imported. See [token handling](../SECURITY.md#token-handling).

## When Upgrades Fail From Old Private/Dev States

Use the operational recovery flow in
[troubleshooting.md](troubleshooting.md), especially:

- `Pairing required / token invalid / Repairs`
- `Reconfigure host or port`
- `Device unreachable during repair`

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
