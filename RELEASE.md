# Release v0.6.8

## Summary

This release adds explicit start and stop button entities for the DHE brush and shower timers and refines timer display limits.

## Changes

- Added explicit `Start brush timer` and `Stop brush timer` button entities.
- Added explicit `Start shower timer` and `Stop shower timer` button entities.
- Timer start buttons send `assign:ste.app.*Timer:activation` with `true`.
- Timer stop buttons send `assign:ste.app.*Timer:activation` with `false`.
- Brush and shower timer duration numbers are limited to a maximum of `20 min`.
- Brush and shower timer remaining sensors display their value as `M:SS`.
- Existing timer activation switches, duration numbers, remaining sensors and reset buttons remain available.
- English and German translations are updated for the new timer buttons.

## Installation via HACS custom repository

Repository URL: `https://github.com/memphi2/ha-dhe-connect`
Category: `Integration`
