# Changelog

## v1.0.7-beta - 2026-05-12 (compared to v1.0.6)

### Added

- Added focused unit coverage for weather, radio, pairing, config-flow and entity helper mappings.
- Added disabled-by-default diagnostics for scald protection status, scald protection limit, device status and a device alarm binary sensor.

### Changed

- Refactored weather, radio, pairing, config-flow and shared entity state mapping into smaller helper modules.
- General error status now shows a `Service nötig` / `Service required` message when DHE status code `34` reports the service-required state.
- Timer duration controls now use the original duration entities as seconds in Home Assistant.
- Bath fill target and remaining volume values now display as whole liters.
- Radio media title now falls back to the station short description before the station name.
- Maximum temperature configuration now supports the full `20` to `50` C device range.
- Weather location selection is enabled by default for new setups.
- Weather period selection now uses Home Assistant's configured timezone.
- German naming now uses `Durchlauferhitzer` for water heating.

## v1.0.6 - 2026-05-11 (compared to v1.0.5)

### Added

- Multi-device support: multiple DHE Connect config entries can now be created in one Home Assistant instance.
- Weather services now support optional `entry_id` targeting for multi-device setups.

### Changed

- Pairing token storage was split per DHE target (`host`/`port`) instead of one global token file.
- Legacy single-device token handling is migrated automatically for existing setups, and the old global token file is consumed during migration.
- Existing installs now keep the legacy `(DOMAIN, host)` device identifier during upgrade while adding the new `host:port` identifier, preventing one-time duplicate device entries.
- Token filenames now cap the host-derived component (with hash fallback) to avoid filesystem `name too long` errors on long FQDNs.
- Connection state is now exposed as translated enum states in Home Assistant (for example `Verbunden` instead of raw `connected`).
- Integration consistency check no longer requires `single_config_entry` in `manifest.json`.

## v1.0.5 - 2026-05-11 (compared to v1.0.4)

### Changed

- Pairing flow was hardened for setup and repair: Home Assistant now requires explicit on-device confirmation before finishing authentication.
- Pairing retries are now bounded to 3 automatic attempts; after that, manual retry is required to avoid reconnect loops.
- Setup pairing/token retrieval now respects the configured setup timeout window (for example 180s).
- Availability behavior is now strict live across core entities (no stale "available" state while runtime data is missing).
- Connection validation was tightened, including IPv6-safe host handling and clearer host/port validation feedback.

### Fixed

- Fixed CI syntax failure caused by a UTF-8 BOM in `config_flow.py`.
- Updated setup/runtime pairing texts to clearly instruct the required device confirmation step.
- Refreshed README and SECURITY documentation for the current pairing and availability behavior.

## v1.0.4 - 2026-05-10

### Added

- Full weather favorites workflow: search, add/remove favorite and select active weather location.
- Full radio favorites workflow: search by text/genre/country/city, add/remove favorite and select station.
- Temperature memory expanded to all 12 slots with sensible defaults (slots 3-12 disabled by default).
- New diagnostic sensors for connection state, reconnect reason, last command age and general temperature error status.
- Lightweight repository validation script and workflow checks for manifest/translations/docs consistency.

### Changed

- Currency, electricity price, water price and CO2 emission moved from entities to the options flow.
- Weather entity attributes now expose clear location data (`city`, `country`, `location`) plus icon metadata.
- Last usage duration now renders as `M:SS`, aligned with timer remaining sensors.
- Entity defaults were cleaned up to reduce device-card noise (advanced diagnostics/long-term stats optional).

### Fixed

- Climate setpoint flow now turns heating on first (if OFF) before writing a new setpoint.
- HVAC mode now follows confirmed `id 33` writebacks instead of optimistic local mode flips.
- General error status now updates immediately on online/offline changes.
- Removed stale/legacy registry entities and old binary-sensor leftovers from active setup.

## v1.0.2 - 2026-05-10

This release focuses on a cleaner device card, better protocol coverage and less noisy diagnostics while keeping the local WebSocket behavior close to the DHE browser UI.

### Added

- Radio media player for current station metadata, playback and volume.
- Weather entity based on the DHE `ste.app.weather:location` forecast payload.
- Bath fill remaining sensor derived from target volume minus current fill volume.
- Disabled-by-default diagnostic entities for observed ODB IDs `22`, `24`, `33` and `34`.

### Changed

- Reduced default entity noise: advanced diagnostics, saving monitor values, configured power and week/year consumption sensors now start disabled.
- Kept radio startup lean by requesting only station, title, play, pairing and volume state; catalog/search/favorites payloads are recognized but not exposed.
- Rounded last usage water and energy values to two decimals.
- Updated README protocol notes, entity tables and troubleshooting guidance for the v1.0.2 entity model.

### Removed

- Removed legacy duplicate device type and unhandled ODB value entities.
- Removed delete buttons for fixed temperature memory slots 1 and 2.

## v1.0.1 - 2026-05-09

### Added

- Added electricity price, water price, CO2 emission and currency controls.
- Added temperature memory controls for up to 12 memory slots, including names, temperatures, preset buttons and delete actions where supported by the device.
- Added saving monitor, last usage, internal temperature and device information sensors.
- Added online status and reconnect count diagnostics.
- Added a switch for the maximum temperature limit using ODB ID 4.

### Changed

- Rounded saving monitor values and clarified inlet/outlet temperature labels.
- Show temperature memory controls only for slots reported by the DHE.
- Default the currency selector to EUR when the device returns an empty currency value.
- Updated README and translations for the expanded entity set and protocol documentation.

### Removed

- Removed unreadable app setting diagnostics, including the maximum temperature override sensor that stayed unknown on supported test devices.
