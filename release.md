# Release [0.7.7] - 2026-05-07

## Included
- Bump integration version to `0.7.7`.
- Optimize runtime callback dispatching by storing listeners as sets to avoid duplicate registrations and reduce list-copy overhead during frequent updates.
- Replace repeated inline writable-option ID sets with a single shared constant for clearer and cheaper membership checks.
- Refresh root and component README notes to document the maintenance/performance cleanup.

## Summary

Performance and maintenance cleanup release with no entity model changes.

## Changes

- Bump integration version to `0.7.7`.
- Keep the current Home Assistant entity set and protocol behavior unchanged.

## Installation via HACS custom repository

Repository URL: `https://github.com/memphi2/ha-dhe-connect`
Category: `Integration`
