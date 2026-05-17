# Changelog

## Unreleased

### Added

- Expanded fake DHE Engine.IO coverage for stored-token authentication, setup pairing, manual token-before-result pairing, rejected pairing and closed-session handling.

### Changed

- Extended the scoped type gate to include the DHE runtime, app-runtime, transport and pairing mixins.

## v1.4.1 - 2026-05-17

### Added

- Expanded the fake DHE Engine.IO test server coverage with a command-level water-heating flow that posts the ODB write, accepts the DHE readback confirmation and verifies the follow-up set-request sync.
- Expanded fake DHE command-level coverage for setpoint readback, temperature-memory generation/readback and radio favorite selection.
- Expanded fake DHE command-level coverage for weather favorite add/remove flows and selected-location readback.
- Expanded the real Home Assistant fixture runtime suite to cover setup, reload, unload, multi-entry service lifetime and climate entity unique-ID separation.
- Expanded Home Assistant fixture coverage for multi-entry service routing, entity-registry stability across reload and runtime availability recovery.
- Expanded Home Assistant fixture coverage for cached weather service candidates and live sensor/reconnect/diagnostic callback updates.
- Added a CI-friendly synthetic Home Assistant recorder smoke fixture that runs the mounted-config smoke path without a live HA test machine.
- Added sanitized synthetic protocol replay fixtures for parser and runtime coverage without storing live DHE captures.

### Changed

- Broadened the scoped type-checking gate from helper and mapping modules to the integration setup module, the composed client facade, Home Assistant platform entities and additional runtime helpers.
- Added explicit Protocol-based command context typing for the DHE command mixins and included those command modules in the scoped type gate.
- Added the config and options flow module to the scoped type gate with an explicit options-client Protocol.
- Added explicit platform-entity type annotations where Home Assistant attributes were previously inferred too narrowly for the wider type gate.
- Added Ruff linting to the GitHub `Validate` workflow so CI now enforces the same lint gate as local release checks.
- Added explicit README notes for unofficial status, trademark use, original artwork and MIT licensing scope.
- Split command retry execution into a dedicated runner mixin so the central client class keeps less transport policy code.
- Slimmed the README into a clearer user-facing entry point and moved detailed validation, HA smoke and release-readiness guidance into `docs/validation.md`.
- Clarified that protocol labels such as `ODB` are source/debugging details and not part of the user-facing entity names.

### Fixed

- Made HA API service smoke turn the radio back off 30 seconds after selecting a test source.
- Made the Home Assistant fixture runtime test self-contained when run directly by ensuring the repository root is importable before loading the custom integration package.

### Validation

- Local test suite: `348 passed`, `22 subtests passed`.
- Integration repository check: `scripts/check_integration.py`.
- Type gate: `scripts/check_typing.py` over 44 modules.
- Ruff: `ruff check custom_components/stiebel_dhe_connect tests scripts`.
- HA-Test smoke: copied to the mounted Home Assistant test config, restarted Home Assistant, verified DHE connection health and ran mounted smoke checks with localhost-token cleanup.
- Release-readiness check prepared with `v1.4.1` tag and GitHub release expected absent.

## v1.4.0 - 2026-05-17

### Added

- Added a scoped type-checking gate so release validation catches typing regressions in the integration package.
- Added a Home Assistant fixture runtime test that loads the integration through a lightweight HA-style setup path.
- Added a fake DHE Engine.IO transport test server to exercise polling, namespace open, authentication and WebSocket upgrade behavior without a physical device.
- Added original mark-safe PNG brand assets for the integration icon and logo.

### Changed

- Bumped the integration version to `1.4.0` for the next stable release.
- Extracted pure DHE client value conversion helpers out of `client.py` to keep the runtime client focused on connection and command behavior.
- Split command feature mixins and runtime app handlers out of the central client modules to keep the hot runtime path easier to review.
- Split diagnostic sensor definitions and config-flow schema builders into dedicated modules.
- Reduced radio and weather recorder-visible attributes so large catalog/search payloads do not churn the Home Assistant database.
- Narrowed RuntimeError transport recovery so only known socket/session shutdown races are handled as reconnectable transport failures.
- Made HA smoke recorder checks tolerant of operational restart windows while still failing high-churn steady-state writes.
- Made HA smoke recorder checks detect device-status water-running windows and completed last-usage windows before applying idle recorder-write limits.
- Pinned external HACS and Hassfest validation actions to commit SHAs for reproducible release checks.
- Added a dedicated troubleshooting guide for pairing, connectivity, recorder churn, favorites, memory slots and debug logs.

### Fixed

- Kept `client.py` below the repository size guard after the previous client split work.
- Enabled current water flow and current power sensors by default for live dashboard visibility.
- Refreshed disabled-by-default sensor values on demand when those entities are enabled while the DHE session is already running.
- Ignored startup/request-read zero placeholders for the diagnostic ODB total and saving values while still accepting runtime zero updates emitted by the DHE.
- Kept diagnostic ODB total and saving sensors available with `unknown` state while waiting for their first real runtime value.
- Clarified ODB heating, hot-water-volume and saving sensor names after comparing them with the DHE web app's possible and actual saving payloads, including new ODB-specific entity keys instead of registry migrations.
- Replaced the scald-protection temperature-limit icon with a visible Home Assistant MDI icon.
- Documented DHE web-interface ODB IDs for total/saving diagnostic values and labelled device status code `2` as water running.
- Tightened command retry handling so unsupported broad RuntimeError cases are no longer treated as command retries.
- Preserved recoverable handling for known aiohttp/WebSocket close races during runtime transport operations.

### Security

- Redacted private host, URL, auth-header, token and credential context from client diagnostics, HA smoke output and release-check command/result output.

### Validation

- Local test suite: `331 passed`, `18 subtests passed`.
- Integration repository check: `scripts/check_integration.py`.
- Type gate: `scripts/check_typing.py`.
- Ruff: `ruff check .`.
- HA-Test smoke: mounted Home Assistant config smoke checks with recorder monitoring and localhost token cleanup.
- GitHub Validate workflow: HACS, Hassfest and repository checks across the merged release-prep PRs.

## v1.3.2 - 2026-05-16

### Added

- Added a reusable Home Assistant API test helper for authenticated restart checks, service smoke tests and localhost test-token cleanup.
- Added a release-readiness helper that bundles version, documentation-link, changelog, tag, GitHub release, clean-tree, whitespace, secret-scan and optional HA smoke checks.
- Added focused regression coverage for closed-session RuntimeError retry behavior, setup-pairing RuntimeError mapping and price rollback failure diagnostics.
- Moved the detailed Socket.IO / Engine.IO / ODB protocol reference out of the README into `docs/protocol.md`.

### Changed

- Bumped the integration version to `1.3.2`.
- Reworked protocol imports to be explicit across platforms instead of relying on broad `client.py` re-exports.
- Extracted shared DHE client exceptions, session/event models, callbacks and value aliases into `client_types.py` so `client.py` stays focused on runtime behavior.
- Narrowed command and config-flow exception handling so programming errors are no longer retried or hidden as generic DHE failures.
- Kept transport-like RuntimeError recovery for reconnect races, including closed aiohttp sessions.
- Slimmed the README by keeping setup, high-level entity and validation guidance there while moving protocol internals and the full entity reference to dedicated documentation.

### Fixed

- Restored recoverable handling for DHE WebSocket/session RuntimeError transport races without broadly swallowing unrelated RuntimeError failures.
- Mapped setup-pairing RuntimeError transport failures into the existing recoverable pairing path.
- Made electricity and water price writes roll back only the components that were actually attempted, including partial-cache cases.
- Preserved the original price write failure while reporting rollback failures, including RuntimeError rollback failures.

### Validation

- Local test suite: `247 passed`, `2 subtests passed`.
- Integration repository check: `scripts/check_integration.py`.
- Ruff: `ruff check custom_components/stiebel_dhe_connect tests scripts`.
- HA-Test private lab: deployed the release-prep branch, restarted Home Assistant and verified the private DHE endpoint stayed connected.
- HA-Test service smoke: `climate.turn_off`, `climate.turn_on`, `media_player.turn_off` and `media_player.select_source`.
- HA-Test recorder monitor: `recorder writes total=0 limit=10` over 90s.
- GitHub Validate workflow: HACS, Hassfest and repository checks.

## v1.3.1 - 2026-05-16

### Changed

- Reduced Home Assistant recorder churn after the `v1.3.0` stable tag by deduplicating repeated state writes for weather, radio, climate, text, number and sensor entities.
- Added mounted Home Assistant smoke checks for entity health, DHE log errors, temporary localhost auth tokens and recorder write volume.
- Made sensor state writes sensitive to recorder-visible attribute changes without re-enabling writes for high-churn chart and saving-monitor payload details.

### Fixed

- Preserved important attribute-only sensor updates that were previously hidden by the write filter.
- Cleared the requested radio-off marker when selecting a new radio source, so a source change cannot leave Home Assistant stuck in an explicit off state.
- Wrote climate state immediately when the inlet temperature crosses into or out of `target_below_inlet`, even while normal inlet telemetry is throttled.

### Validation

- Local test suite: `231 passed`.
- Integration repository check: `scripts/check_integration.py`.
- HA smoke after restart: `scripts/ha_test_smoke.py --config /mnt/ha-test-config --include-fault-log`.
- Idle HA recorder monitor: `recorder writes total=0 limit=10` over 90s.
- Live water HA recorder monitor: `recorder writes total=0 limit=10` over 300s with water on/off.
- Service interaction HA recorder monitor: `recorder writes total=0 limit=10` over 180s while exercising `climate.turn_off`, `climate.turn_on`, `media_player.turn_off` and `media_player.select_source`.
- GitHub Validate workflow: HACS, Hassfest and repository checks.

## v1.3.0 - 2026-05-16

### Added

- Added Home Assistant `climate.turn_on` / `climate.turn_off` support by mapping the DHE water-heating control to HVAC `heat` / `off`.
- Added regression coverage for climate on/off, set-temperature auto-enable, WebSocket heartbeat/control pings, timer write paths, memory-slot recreation and recorder write filtering.
- Added a reusable mounted-HA smoke check for entity health, recorder churn, DHE log errors and temporary localhost auth tokens.

### Changed

- Reduced recorder churn further for diagnostic, climate, saving-monitor, consumption and error-status entities.
- Refreshed nominal power on every session so derived power readings recover cleanly after reconnects.
- Hardened weather and radio state handling, including local forecast dates, radio off state and favorite-list drift.
- Simplified rounding and immutable class/test fixtures flagged by focused Ruff checks.
- Improved shared Home Assistant test stubs so tests remain isolated regardless of execution order.

### Fixed

- Dedupe repeated unavailable (`None`) measurements in the client before notifying entity callbacks.
- Guarded release-note source checks so legacy `info.md` release notes cannot be accidentally restored.
- Fixed German currency label encoding coverage.

### Validation

- Local test suite: `227 passed`.
- Integration repository check: `scripts/check_integration.py`.
- HA smoke check: `scripts/ha_test_smoke.py --config /mnt/ha-test-config --include-fault-log --monitor-seconds 90`.
- GitHub Validate workflow: HACS, Hassfest and repository checks.
- Live HA test: copied to the Home Assistant test instance, restarted HA, verified DHE entities, and exercised `climate.turn_off` / `climate.turn_on` from `heat -> off -> heat` without DHE error-log entries.

## v1.2.3 - 2026-05-16

### Changed

- Added climate `turn_on` / `turn_off` support by mapping to HVAC `heat` / `off`.
- Weather/radio remove flows now avoid index drift by refreshing favorites only on initial options-form render.
- Weather favorite add/remove/toggle now accepts raw `location_id` values more robustly.
- Reduced recorder/state-write noise for high-churn telemetry sensors with delta/time filtering.
- Saving-monitor updates now refresh only the changed category payload, and climate inlet/outlet telemetry writes are throttled by delta/time.

### Fixed

- Corrected temperature-memory confirmation generation baseline handling to avoid false confirmations.

### Tests

- Added regression coverage for stricter temperature-memory confirmation behavior.
- Added sensor recorder/write-filter coverage for noisy telemetry entities.
- Added regression coverage for saving-monitor category refresh behavior and climate telemetry write throttling.

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
