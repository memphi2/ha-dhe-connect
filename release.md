# Release [0.7.10] - 2026-05-08

## Included
- Bump integration version to `0.7.10`.
- Request all currently known web UI startup values best-effort after required entity seed values.
- Cache optional non-entity app and ODB startup values internally.
- Reuse precomputed timer command sets in the runtime event path.
- Simplify callback removal.
- Refresh docs for the broader startup reads.

## Summary

Optimized startup value read release.

## Changes

- Required entity startup reads keep their previous behavior.
- Optional startup reads cover remaining readable ODB ID `4`, temperature memory, consumption volume format and last usage, wellness programs and maximum override. ODB ID `66` stays write-only.
- Optional read failures are logged at debug level and do not abort the runtime session.
- App timer command matching uses a precomputed command set instead of rebuilding a set during every event.

## Installation via HACS custom repository

Repository URL: `https://github.com/memphi2/ha-dhe-connect`
Category: `Integration`
