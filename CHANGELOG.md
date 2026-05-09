# Changelog

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
