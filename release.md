# Release [0.7.8] - 2026-05-07

## Included
- Bump integration version to `0.7.8`.
- Add DHE temperature memory preset buttons for memory slots 1 and 2.
- Add configurable temperature memory number entities.
- Request temperature memory values and additional known web UI startup values during session initialization.
- Refresh root and component README notes plus translations for the new controls.

## Summary

Temperature memory control release with broader startup value initialization.

## Changes

- Temperature memory buttons use ODB ID `66` values `10620` and `10650`.
- Temperature memory numbers write through `assign:ste.common.temperature:memory` with `operation: add_change`.
- Additional startup reads cover temperature memory, volume format, last usage, wellness programs, max override and time formats.

## Installation via HACS custom repository

Repository URL: `https://github.com/memphi2/ha-dhe-connect`
Category: `Integration`
