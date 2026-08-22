# Changelog

## Unreleased

- No changes yet.

## v2.0.8 - 2026-08-22

Local maintenance version for the next release cycle after v2.0.7.

## v2.0.7 - 2026-08-22

Maintenance release for DHE token persistence and migration hardening.

- Store DHE pairing tokens in config-entry data, migrate well-formed legacy
  token files on setup/retarget, and delete the old per-target token files
  after migration.
- Prefer a destination target's legacy token when retargeting if both old and
  new target token files exist.

## v2.0.6 - 2026-07-09

Local maintenance version for the next release cycle after v2.0.5.

- Avoid creating idle weather forecast-listener tasks when no Home Assistant
  forecast listeners are registered, and coalesce concurrent forecast listener
  notifications into one follow-up task.
- Coalesce connected-state and auth-failure diagnostic cleanup scheduling so
  high-frequency runtime diagnostics cannot create unbounded Home Assistant
  background tasks.
- Track delayed cleanup tasks in replaceable runtime slots instead of retaining
  one unload callback per scheduled task.

## v2.0.5 - 2026-07-09

Maintenance release for long-term Home Assistant compatibility and runtime
memory hygiene.

- Capped fallback radio source retention when station updates arrive without a
  favorites payload, preventing the media player entity from keeping an
  unbounded list of previously seen stations.
- Added unload coverage to verify Home Assistant removes all runtime callbacks
  when the config entry is unloaded.
- Declared the validated minimum supported Home Assistant version in HACS
  metadata, README and validation docs so release support boundaries stay
  explicit.
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
