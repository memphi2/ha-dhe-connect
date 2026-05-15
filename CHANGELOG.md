# Changelog

## v1.2.2b1 - 2026-05-15

### Added

- Expanded regression coverage for weather favorite toggling and recorder-safe sensor attributes.
- Added shared lightweight Home Assistant/aiohttp stub coverage for dependency-free unit tests.

### Changed

- Run options-flow connectivity checks only when host or port changed.
- Mark high-volume dynamic sensor attributes (`chart`, `possible`, `real`, `consumption`, `activation_rate`) as unrecorded for recorder protection.
- Include host and port in pairing notification IDs to avoid collisions across multiple configured DHE targets.
- Create pairing token temporary files with restrictive `0600` permissions from the first write.

### Fixed

- Restored German translations with proper umlauts and special characters.
- Accept awaitable weather listener update hooks across Home Assistant versions.
- Ignore `null` entries in radio string catalog normalization.
- Harden weather favorite handling when favorite-list refresh times out or the DHE does not apply favorite changes.
- Roll back split price writes when the second ODB write fails.
- Require confirmed readback after setting a temperature-memory slot.

### Beta notes

- This is a beta release intended for validation before the next stable patch.

## v1.2.1 - 2026-05-14

### Changed

- Reject embedded ports in URL-style host input and require the dedicated port field.
- Require a fresh pairing/auth validation when options change the DHE host or port.
- Clear radio station metadata when the DHE publishes no active station, while keeping known favorites.
- Use Home Assistant media-player state enums when available.
- Schedule weather forecast listener updates only when Home Assistant returns a coroutine.
- Run unit tests explicitly in CI before the repository integration checks.

### Tests

- Added host normalization coverage for URL, raw host:port and IPv6 port inputs.
- Added target-change coverage for options-flow connection changes.
- Added explicit weather forecast date semantics coverage.

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
