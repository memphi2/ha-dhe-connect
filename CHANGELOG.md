# Changelog

## Unreleased

### Compatibility

- Support Home Assistant 2026.10.4 and newer; use v2.0.9 on HA 2026.10.1-2026.10.3.
- Use native climate temperature attributes with a narrow adapter for HA 2026.10.
- Keep entity subscriptions active across in-place entity ID changes.
- Use exception-based config-entry setup and unload results on HA 2026.11.
- Construct device metadata through Home Assistant's DeviceInfo API.

### Fixes

- Require fresh device values after reconnecting before restoring availability,
  and expire the reconnect grace period while startup confirmation is pending.
- Clear stale authentication errors after a successful runtime recovery.
- Publish the final filtered sensor value when its update interval expires.
- Update weather search results independently of recorder filtering, validate
  bounded integer inputs, and keep adding a favorite separate from selecting it.
- Serialize discovery-cache loading and atomic writes to avoid lost updates.
- Bind Repairs to their config entry and prevent recreation after its removal.

### Maintenance

- Centralize paired HA core/test-helper baselines and test both supported APIs.
- Verify installed core/helper provenance and resolve matching latest-HA pairs.
- Gate lifecycle/reconnect/idle task and memory growth with a loopback soak test.
- Group routine tool updates quarterly while keeping security updates separate.
- Document config-entry token storage and device-side revocation accurately.
- Classify the integration as a water heater for catalog discovery.

## v2.0.10 - Unreleased

Release preparation for Home Assistant 2026.11. Changes are listed above until
the final stable HA baseline has passed validation. No release date is set yet.

## v2.0.9 - 2026-10-14

Maintenance release for Home Assistant 2026.10 compatibility.

- Require Home Assistant 2026.10.1 or newer.
- Keep setup, options, repairs, and service actions compatible with Home
  Assistant 2026.10's validation APIs.

## v2.0.8 - 2026-09-06

Maintenance release for standard HACS installation and long-term Home Assistant
weather compatibility.

- Document installation from the default HACS catalog after the repository was
  accepted into HACS, replacing the obsolete custom-repository setup steps.
- Keep weather forecast updates idle-efficient while using Home Assistant's
  supported subscription lifecycle instead of private listener state.

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
