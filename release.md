# Release [0.7.9] - 2026-05-07

## Included
- Bump integration version to `0.7.9`.
- Fix DHE temperature memory number writes for single-object `assign:ste.common.temperature:memory` responses.
- Stop temperature memory preset buttons from blocking on generic ODB ID `66` write confirmation.
- Keep optional web UI startup reads best-effort so runtime updates and writes can continue.

## Summary

Runtime hotfix for the temperature memory control release.

## Changes

- Temperature memory buttons still use ODB ID `66` values `10620` and `10650`, but no longer wait for a generic ID `66` readback before returning.
- Temperature memory numbers write through `assign:ste.common.temperature:memory` with `operation: add_change` and update from both list and object responses.
- Additional startup reads cover temperature memory, volume format, last usage, wellness programs, max override and time formats without aborting startup if an optional request fails.

## Installation via HACS custom repository

Repository URL: `https://github.com/memphi2/ha-dhe-connect`
Category: `Integration`
