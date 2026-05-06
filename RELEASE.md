# Release v0.7.1

## Summary

Bugfix release for Home Assistant startup with app timer switch entities.

## Changes

- Fix `AttributeError: 'StiebelDHEAppTimerSwitchDescription' object has no attribute 'device_class'` during switch entity setup.
- Make the app timer switch description extend Home Assistant's `SwitchEntityDescription`.
- Keep the `0.7.0` documentation cleanup and current timer behavior unchanged.

## Installation via HACS custom repository

Repository URL: `https://github.com/memphi2/ha-dhe-connect`
Category: `Integration`
