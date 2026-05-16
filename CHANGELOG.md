# Changelog

## v1.2.3 - 2026-05-16

### Changed

- Added climate `turn_on` / `turn_off` support by mapping to HVAC `heat` / `off`.
- Weather/radio remove flows now avoid index drift by refreshing favorites only on initial options-form render.
- Weather favorite add/remove/toggle now accepts raw `location_id` values more robustly.
- Reduced recorder/state-write noise for high-churn telemetry sensors with delta/time filtering.

### Fixed

- Corrected temperature-memory confirmation generation baseline handling to avoid false confirmations.

### Tests

- Added regression coverage for stricter temperature-memory confirmation behavior.
- Added sensor recorder/write-filter coverage for noisy telemetry entities.

## v1.2.2b1 - 2026-05-16

### Added

- Added dedicated weather favorite services for add/remove flows, plus safer validation paths in regression tests.
- Added shared Home Assistant/aiohttp stubs used by multiple test suites.
- Added tests for options flow currency no-op behavior and stricter temperature-memory confirmation checks.

### Changed

- Options-flow now only performs connectivity/pairing checks when host or port actually changed.
- Pairing notifications are now scoped by host+port; legacy pairing notification IDs are cleaned up to avoid stale alerts.
- Pairing token writes now use `0600` permissions from creation.
- Host/port input handling was tightened so embedded ports are rejected at config entry time.

### Fixed

- Restored proper UTF-8 German text in pairing confirmation UI.
- Made weather and radio favorite operations safer against stale cache and failed refresh scenarios.
- Improved awaitable handling for weather forecast update hooks.
- Made price writes atomic (euros/cents) with rollback on partial write failure.
- Enforced readback confirmation for temperature-memory value and name writes.
- Improved radio catalog normalization by ignoring `null` entries.

### Tests

- Added/extended tests for URL/host:port/IPv6 host parsing.
- Added coverage for options-flow target-change behavior.
- Added explicit weather forecast date-semantics and stale favorite-list edge-case coverage.
- Added regression coverage for currency, price, and temperature-memory write confirmations.

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
