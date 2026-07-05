# Changelog

## v2.0.5 - 2026-07-05

Maintenance release for long-term Home Assistant compatibility.

- Replaced the deprecated Home Assistant percentage unit constant with the
  literal percent unit used by current Home Assistant releases.
- Added a monthly scheduled check against the latest Home Assistant package
  while keeping the pinned baseline fixture for reproducible validation.
- Kept HACS and Hassfest validation on the scheduled repository workflow.

## v2.0.4 - 2026-06-20

Initial release of DHE Connect for Home Assistant.

### Initial Release

- Added a local Home Assistant integration for DHE Connect instantaneous water
  heaters.
- Included climate control, live water and power sensors, timers, radio,
  weather and diagnostics.
- Added documentation, examples and validation checks for the stable release
  baseline.
