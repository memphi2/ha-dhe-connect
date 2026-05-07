# Release [0.7.9] - 2026-05-07

## Included
- Bump integration version to `0.7.9`.
- Add box-mode number entities for DHE temperature memory slots 1 and 2.
- Change brush and shower timer duration numbers to box mode.
- Add best-effort temperature memory value reads.
- Refresh docs and translations for the new number entities.

## Summary

Temperature memory configuration and timer duration box-input release.

## Changes

- Temperature memory slot 1 writes through `assign:ste.common.temperature:memory` with memory ID `0`.
- Temperature memory slot 2 writes through `assign:ste.common.temperature:memory` with memory ID `1`.
- Temperature memory values are requested best-effort at startup and after memory writes.
- Brush and shower timer duration controls use Home Assistant number box mode instead of slider mode.

## Installation via HACS custom repository

Repository URL: `https://github.com/memphi2/ha-dhe-connect`
Category: `Integration`
