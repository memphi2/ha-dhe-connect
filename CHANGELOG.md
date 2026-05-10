# Changelog

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
