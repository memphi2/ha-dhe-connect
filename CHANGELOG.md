# Changelog

## v1.2.0 - 2026-05-14

### Added

- Initial HACS custom integration release for STIEBEL ELTRON DHE Connect devices.
- Fully local Socket.IO / Engine.IO v3 client with browser-style polling, WebSocket upgrade, heartbeat handling and reconnect diagnostics.
- UI config flow with on-device pairing, per-device token storage, multi-device support and duplicate host/port protection.
- Climate control for DHE target temperature with limits that respect the configured physical `Tmax` jumper and the active child-safety limit.
- Controls for Eco mode, Eco flow limit, bath fill, child safety, wellness programs, brush timer, shower timer and temperature memories.
- Radio media player with station metadata, playback, volume, favorites and search helpers for text, genre, country and city catalogs.
- Weather entity for DHE forecast payloads, including favorite location selection and mapped Home Assistant weather conditions.
- Consumption, saving, diagnostic, device information, connection state, error status and ODB protocol sensors with conservative default visibility.
- Options flow for device connection settings, scald-protection configuration, currency, price and radio/weather preferences.
- Repository validation workflow for HACS, Hassfest and local integration consistency checks.

### Notes

- This release is treated as the first public baseline. Earlier development snapshots are intentionally not listed as release history.
- If Home Assistant was used with pre-release development builds, remove the old integration entry/device once and add it again so Home Assistant creates fresh entity registry entries.
