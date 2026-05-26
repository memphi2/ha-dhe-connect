# Changelog

## Unreleased

- No changes yet.

## v2.0.2 - 2026-05-26

### Runtime Resilience

- Added a stale-runtime watchdog for long-lived sessions that remain connected
  but stop receiving device payloads.
- After prolonged runtime silence, the integration now sends a lightweight ODB
  probe and forces one reconnect when that probe stays unanswered.
- Added watchdog tests for probe send, probe-ack reset, probe-timeout reconnect
  and probe-command transport failure paths.

### Flow and Runtime Hardening

- Added shared connection helper module for setup/options/reconfigure paths to
  reduce duplicated normalization/update logic.
- Made token preservation on host/port retarget best-effort and non-fatal
  (I/O copy errors no longer break reconfigure flows).
- Added focused tests for token-preserve copy/skip/error behavior.
- Improved callback error logging to include callback identity and added
  regression coverage that one failing callback does not block others.

### Release and Validation Gates

- Hardened repository checks so README documentation validation is based on
  required link targets (layout-independent) instead of fixed table rows.
- Added stable-release changelog language guards to prevent non-stable wording
  in stable sections.
- Added `scripts/check_release_consistency.py` and wired it into CI plus
  `release_check --run-local-checks`.
- Made `release_check --expect-tag skip` development-friendly by allowing
  non-empty `Unreleased` sections while keeping strict release-tag checks.
- Fixed GitHub hygiene scan compatibility with GH CLI versions without
  `gh api --slurp` support.
- Added `scripts/check_privacy_markers.py` and CI/release gates to block
  lab-specific aliases, private lab subnet fragments and JWT-like token leaks in
  tracked files.
- Added `scripts/check_translation_keys.py` to enforce required user-facing
  flow/repairs/service translation keys in `en.json` and `de.json`.
- Tightened the coverage gate by moving `pairing_helpers.py` into the measured
  deterministic module set and extending pairing helper tests accordingly.
- Added long-run reconnect supervisor churn tests to harden deterministic
  reconnect/backoff/grace behavior.
- Refactored schema suggested-value application out of `config_flow.py` into
  `config_flow_schemas.py` to keep flow orchestration code slimmer.
- Added typed payload shape definitions in `payload_types.py` while keeping
  existing runtime payload aliases stable for compatibility.

## v2.0.1 - 2026-05-25

Stable release for the v2 line. This release keeps public entity IDs,
unique IDs and DHE protocol behavior stable.

### Runtime/Auth and Pairing Hardening

- Refined transport auth/token request handling to reduce stale or ambiguous
  runtime auth states.
- Hardened pairing/token validation paths and related reconnect handling.

### Flow and Runtime Cleanup

- Cleaned up setup/options/runtime helper paths to reduce legacy fallback
  ballast.
- Tightened runtime state/write handling for better recorder hygiene and
  deterministic behavior during reconnect/auth transitions.

### Legacy Policy for v2 Line

- This release does not include compatibility shims for legacy/private migration
  edge cases from older development snapshots.
- If an older private/dev setup behaves inconsistently after upgrade, remove
  and re-add the integration cleanly.

### Tests and Regression Safety

- Added dedicated eco-flow command regression tests.
- Expanded deterministic test coverage across pairing, weather favorites,
  config-flow defaults, recorder attributes and helper behavior.
- Updated HA smoke helper checks to match current runtime/recorder expectations.

## v1.8.4 - 2026-05-24

Bugfix release for the v1.8 line. This release keeps public entity IDs, unique
IDs and DHE protocol behavior stable.

### Entity Naming and Translations

- Removed hardcoded wellness switch names from switch descriptions so Home
  Assistant consistently uses translation keys for localized entity labels.
- Restored German wellness program names in translations:
  `Erkältungsvorbeugung`, `Wintererfrischung`, `Sommer-Fitness`,
  `Durchblutungsförderung`.
- Updated wellness description tests to enforce translation-driven naming
  behavior and avoid regressions.

### Validation

- `.venv/bin/python scripts/check_coverage.py`:
  `722 passed`; scoped integration coverage gate `96%`.
- `.venv/bin/python scripts/check_integration.py`:
  `Ran 636 tests ... OK`; `integration checks ok`.
- `.venv/bin/python scripts/check_deprecations.py`:
  `deprecation guard ok`.
- `.venv/bin/python scripts/check_typing.py`:
  `Success: no issues found in 74 source files`.
- `.venv/bin/python -m ruff check custom_components/stiebel_dhe_connect tests scripts`:
  `All checks passed!`.
- `.venv/bin/python scripts/release_check.py --run-local-checks --allow-dirty --expect-tag absent --expect-github-release absent`:
  `release check ok` (manifest/README/changelog/version gates passed; local tag
  and GitHub release for `v1.8.4` are absent).

## v1.8.3 - 2026-05-23

Release consistency update for the v1.8 line. This release keeps public entity
IDs, unique IDs and DHE protocol behavior stable.

### Runtime and Discovery Consistency

- Zeroconf prompt suppression now only applies when an existing DHE config
  entry is present, preventing stale-cache suppression on fresh setups.
- Runtime no longer requests `get:ste.common.temperature:maxOverride` after
  child-safety updates; bridge handling is now explicit one-way device action.
- Radio runtime no longer infers playback from station/title metadata updates;
  `playing` now follows real radio play-state messages or successful HA actions.

### Entity Defaults and Naming

- Enabled the bridge max-override button by default.
- Added a wellness switch unique-id migration path from
  `wellness_winter_refresh` -> `wellness_winter_pick_me_up` and
  `wellness_circulation_support` -> `wellness_circulation_boost`, so existing
  installs upgrade cleanly without duplicate entities.
- Wellness program naming is now canonicalized to fixed program labels for the
  known IDs (`Cold prevention`, `Winter pick-me-up`, `Summer fitness`,
  `Circulation boost`) and aligned across protocol/constants/translations.
- Updated documentation defaults so inlet/outlet temperature and device status
  are explicitly listed as enabled by default.

### Tests and Regression Safety

- Added a zeroconf regression test to ensure discovery prompts are not
  suppressed without an existing config entry.
- Added targeted runtime tests for child-safety/bridge behavior without
  max-override readback polling.
- Added targeted runtime tests for radio station/title updates that must not
  infer playback state.
- Expanded protocol/sensor/wellness tests for canonical naming and runtime
  mapping consistency.

### Validation

- `.venv/bin/python scripts/check_coverage.py`:
  `712 passed`; scoped integration coverage gate `96%`.
- `.venv/bin/python scripts/check_integration.py`:
  `Ran 627 tests ... OK`; `integration checks ok`.
- `.venv/bin/python scripts/check_deprecations.py`:
  `deprecation guard ok`.
- `.venv/bin/python scripts/check_typing.py`:
  `Success: no issues found in 74 source files`.
- `.venv/bin/python -m ruff check custom_components/stiebel_dhe_connect tests scripts`:
  `All checks passed!`.
- `.venv/bin/python scripts/release_check.py --run-local-checks --allow-dirty --expect-tag absent --expect-github-release absent`:
  `release check ok`.
- HA live smoke on test system (`HA-TEST`) via
  `scripts/ha_test_api.py --service-smoke --entity-smoke --timer-smoke`:
  service smoke passed, entity smoke passed, timer smoke skipped because the
  timer-remaining entity is disabled by integration defaults.
- Additional HA live weather-service check:
  `search_weather_location`, `select_weather_location`,
  `add_weather_favorite`, `remove_weather_favorite` executed and restored to the
  previous location/favorites state.

## v1.8.2 - 2026-05-22

Release hardening update for the v1.8 line. This release keeps public entity
IDs, unique IDs and DHE protocol behavior stable.

### Runtime and Flow Robustness

- Config-flow/setup hardening for stale scan state and stale pairing-pending data.
- Repairs flow hardening for stale or mismatched repair issue payloads and
  missing-entry re-check during confirmation.
- Service-layer hardening for malformed weather `result_number` payloads with
  translated Home Assistant validation errors.

### Replay and Regression Safety

- Added deterministic runtime edge-case replay tests for malformed runtime
  payloads, invalid ODB payload shapes and closed-session reconnect signaling.

### Diagnostics and Validation Hygiene

- Extended diagnostics redaction for additional URL/URI/origin key variants.
- Expanded repository validation guards:
  - replay fixture inventory/schema checks in `scripts/check_integration.py`
  - translation structure parity checks between `en.json` and `de.json`
  - additional deprecated HA API guard patterns in `scripts/check_deprecations.py`

### Validation

- `.venv/bin/python -m pytest -q`: `705 passed`.
- `.venv/bin/python -m pytest -q tests/test_00_ha_fixture_runtime.py -k "repair or reauth or reconfigure"`:
  `28 passed`.
- `.venv/bin/python scripts/check_coverage.py`: `705 passed`; scoped coverage gate `96%`.
- `.venv/bin/python scripts/check_integration.py`: `integration checks ok`.
- `.venv/bin/python scripts/check_typing.py`:
  `Success: no issues found in 74 source files`.
- `.venv/bin/python scripts/check_deprecations.py`: `deprecation guard ok`.
- `.venv/bin/python -m ruff check custom_components/stiebel_dhe_connect tests scripts`:
  `All checks passed!`.
- `.venv/bin/python scripts/ha_test_api.py --url http://HA-TEST:8123 --access-token-env HA_TEST_TOKEN --service-smoke --entity-smoke --timer-smoke`:
  service smoke passed, entity smoke passed, timer smoke passed.

## v1.8.1 - 2026-05-21

Patch release preparation for the v1.8 line. This release keeps public entity
IDs, unique IDs and DHE protocol behavior stable.

### Security and Privacy

- Extended diagnostic redaction to raw IPv6 addresses and removed raw target
  details from pairing notification identifiers.
- Reduced private-context exposure in debug/warning paths.

### Validation Hygiene

- Added a repository-owned deprecation guard to CI and release validation. The
  guard fails on deprecated APIs or warning-suppression settings in this repo
  instead of filtering warnings away.
- Raised CI dependency floors for the Home Assistant fixture stack to current
  Python 3.14-compatible versions.
- Disabled the pytest GitHub-annotation plugin while keeping pytest warning
  output visible in logs, so third-party deprecations are not duplicated as
  repository annotations.
- Extended the deprecation guard to README, changelog and documentation files.
- Made the HA live timer smoke skip missing or disabled timer entities with a
  clear info result instead of aborting the complete smoke round on a 404.

### Performance

- Reused a compiled Socket.IO frame matcher in the client transport parser.

### Robustness

- Restored switch states are written immediately during startup even when
  measurement replay is disabled, preventing stale switch state after reloads.
- Kept climate diagnostics attributes fresh while the configured setpoint remains
  below the inlet temperature, without re-enabling generic high-churn telemetry
  writes.

### Discovery

- Improved Zeroconf/auto-discovery display names so Home Assistant can show a
  per-device title instead of falling back to the integration domain name.
- Preferred device-provided discovery properties for the setup name and ignored
  technical service/domain placeholders such as `stiebel_dhe_connect`.
- Added config-flow title placeholders for discovered setup flows.

### Diagnostics

- Removed the redundant `web_app_version` field from the diagnostics export.
  The same user-facing version remains available as `protocol_version`.
- Filtered `web_app_version` from diagnostic device-info key summaries to avoid
  reintroducing the duplicate field indirectly.
- Updated the firmware-matrix instructions to refer to the protocol version in
  diagnostics.

### Validation

- `.venv/bin/python -m pytest -q`: `686 passed`.
- `python3 -m pytest tests/test_config_flow_defaults.py -q`: `30 passed`.
- `.venv/bin/python -m pytest tests/test_00_ha_fixture_runtime.py -q -k "zeroconf_flow_accepts_realistic_discovery_payload_variants or user_flow_can_select_in_progress_zeroconf_discovery"`:
  `7 passed`.
- `.venv/bin/python -m pytest tests/test_diagnostics.py -q`: `4 passed`.
- `.venv/bin/python -m pytest tests/test_translations.py tests/test_check_integration.py -q`:
  `11 passed`.
- `.venv/bin/python -m ruff check custom_components/stiebel_dhe_connect/config_flow.py custom_components/stiebel_dhe_connect/config_flow_discovery.py custom_components/stiebel_dhe_connect/diagnostics.py tests/test_config_flow_defaults.py tests/test_diagnostics.py`:
  `All checks passed!`.
- `.venv/bin/python scripts/check_typing.py`:
  `Success: no issues found in 70 source files`.
- `.venv/bin/python scripts/check_integration.py`: `integration checks ok`.
- `.venv/bin/python scripts/release_check.py --run-local-checks --expect-tag absent --expect-github-release absent`:
  `release check ok`; tag and GitHub release for `v1.8.1` are absent.
- `.venv/bin/python scripts/ha_test_api.py --url http://HA-TEST:8123 --service-smoke --entity-smoke --timer-smoke`:
  service smoke passed, entity smoke passed, timer smoke skipped disabled timer
  remaining entities cleanly.

## v1.8.0 - 2026-05-21

Platinum-preparation update for the custom integration. This release keeps the
public Home Assistant entity IDs, unique IDs and DHE protocol behavior stable.
It is not an official Home Assistant Core certification.

### Release Hygiene

- Switched the README release badge to tag-based semver sorting so the shown
  release no longer sticks to an outdated older version.

### Maintainability

- Refactored Zeroconf discovery conflict abort handling in `config_flow.py`
  into a shared helper to reduce duplicated conflict-path logic.
- Refactored weather service handlers in `__init__.py` to use one shared
  location-resolution helper for add/toggle/remove/select actions.
- Refactored subnet-scan value steps in `config_flow.py` to use one shared
  CIDR/network-mask input helper while keeping behavior unchanged.
- Added a compatibility fallback test for translated Home Assistant action
  errors when translation kwargs are not supported by the exception signature.

### Platinum Typing Preparation

- Added `docs/platinum_prep.md` and linked it from README/validation docs to
  document the strict-typing and runtime-hardening path toward Platinum
  readiness.
- Hardened the typing gate by enabling mypy `warn_return_any` and
  `warn_unused_ignores`, and fixed the resulting no-any-return issues across
  setup, diagnostics, transport and service helper paths.
- Hardened the typing gate further with mypy unreachable-code,
  redundant-cast, strict-equality, no-implicit-optional, no-untyped-generics
  no-untyped-calls, no-incomplete-defs, extra-checks and untyped-body checks,
  and made `scripts/check_typing.py` fail if any integration module is skipped
  by the scoped mypy file list.
- Switched the typing gate to `strict = true` with normal import following and
  no broad missing-import suppression, and cleaned up HA typing mismatches
  without changing runtime protocol behavior.
- Aligned the mypy target with the Python 3.14 CI runtime so current Home
  Assistant dependency syntax is parsed consistently while every integration
  module stays in the strict file gate.
- Added the first `disallow_untyped_defs` module group gate (helpers,
  connectivity, diagnostics and pairing-validation utilities) as a controlled
  step toward Platinum strict typing.
- Expanded the same `disallow_untyped_defs` gate to `config_flow` and `switch`
  by adding full step-method return annotations and explicit switch action
  argument typing.
- Finalized this typing round by enabling `disallow_untyped_defs` globally in
  the mypy profile for the integration module set.
- Added explicit Protocol-based mixin contracts for command, transport,
  runtime, connection-state and diagnostics client surfaces, with type-only
  structural assertions against the concrete `DHEClient`.

### Quality Evidence

- Expanded Gold evidence documentation with a firmware/user evidence template,
  icon-translation status notes and a repository check that enforces these
  sections.
- Recorded today's real live device evidence (`2026-05-21`) for
  `DHE Connect 18/21/24` in `docs/firmware_matrix.md` with explicit scope.

### Runtime And Protocol Notes

- Exposed ODB ID `32` (`ODB_Wellness_Zeit_Norm`) as a disabled diagnostic
  sensor (`wellness_runtime_normalized`) with translations and protocol/entity
  documentation updates.
- Recorded the real live check for ODB ID `32`: it counts wellness runtime in
  seconds while active and returns to `0` when stopped.
- Adjusted ODB `32` startup behavior so the new wellness-runtime sensor is
  available with `0` when connected without a cached runtime value (instead of
  `unavailable`).
- Removed the wellness-runtime sensor `state_class` to avoid long-term
  statistics writes for this high-churn diagnostic runtime value.
- Documented the intentionally ignored DHE web-interface wellness progress
  command.
- Removed the non-working DHE currency option and app-level currency handling
  from the options flow while keeping price and CO2 settings.
- Added deterministic runtime guards for unknown radio payloads, malformed
  weather payloads and reconfigure behavior during reconnect grace.
- Extended diagnostics redaction to WebSocket URLs so `ws://` and `wss://`
  transport details are sanitized like HTTP URLs.

### Validation

- `python scripts/check_typing.py`: `Success: no issues found in 70 source files`.
- `python -m ruff check custom_components/stiebel_dhe_connect tests scripts`:
  `All checks passed!`
- `python scripts/check_integration.py`: `556` tests ran (`OK`);
  `integration checks ok`.
- `python scripts/check_coverage.py`: `633 passed`; scoped integration coverage
  gate `96%`.
- `python scripts/release_check.py --run-local-checks --expect-tag absent --expect-github-release absent`:
  `release check ok`; tag and GitHub release for `v1.8.0` are absent.

## v1.7.0 - 2026-05-21

Gold-core-oriented release-preparation update for the custom integration.
This is not an official Home Assistant Core certification.

### Home Assistant Repairs

- Fixable Repairs issues for rejected/stored-token runtime failures:
  `pairing_required` and `token_invalid`.
- Repairs fix flow validates fresh local pairing via the same pairing validation
  path used by setup/reauth.
- Repairs issues are cleared automatically after recovered authenticated
  connection.
- Repairs reload the existing config entry and do not create a new device/entity
  structure.

### Reconfigure Flow

- Existing config entry can update host, port, display name and internal
  scald-protection/Tmax setting through the Home Assistant reconfigure UI.
- Host/port changes validate reachability before apply.
- Duplicate target prevention blocks moving one entry onto another entry target.
- Existing token file is preserved conservatively on retarget; no token deletion
  is performed by reconfigure.
- Reconfigure updates and reloads the existing config entry.

### Quality Scale Evidence

- `custom_components/stiebel_dhe_connect/quality_scale.yaml` tracks
  Bronze/Silver/Gold-core rules with explicit rule-to-evidence mapping.
- Silver rules are tracked as `done` or documented `exempt` where applicable.
- Gold-core-oriented evidence is documented for diagnostics, discovery,
  discovery-update-info, reconfiguration-flow and repair-issues without claiming
  official HA-Core certification.
- User-facing DHE action errors are translation-key based in English and German.
- Added dedicated Gold support docs:
  `docs/examples.md`, `docs/use-cases.md`, `docs/known_limitations.md`.

### Branding

- The Home Assistant UI integration name remains `DHE Connect` for concise
  device labels.
- Repository/legal documentation remains explicitly unofficial and
  non-vendor-endorsed.

### Tests And Validation Scope

- HA fixture tests cover Repairs/Repair flow behavior, reauth, reconfigure,
  unload/reload and multi-entry behavior.
- Coverage gate remains enforced via `pytest-cov` for deterministic integration
  modules (`>=95%` threshold).
- Repository validation includes `check_integration`, `check_typing`, Ruff and
  `release_check`.

### Validation

- `python scripts/check_coverage.py`: `621 passed`; scoped integration coverage
  gate `95%`.
- `python scripts/check_integration.py`: `550` tests ran (`OK`);
  `integration checks ok`.
- `python scripts/check_typing.py`: `Success: no issues found in 69 source files`.
- `python -m ruff check custom_components/stiebel_dhe_connect tests scripts`:
  `All checks passed!`
- `python scripts/release_check.py --run-local-checks --expect-tag absent --expect-github-release absent`:
  `release check ok`.

## v1.6.0 - 2026-05-20

Initial public release of `DHE Connect (Unofficial)` after the repository
cleanup. This release is prepared against the Home Assistant Quality Scale
Silver rule set as a custom integration; it is not an official Home Assistant
core integration certification.

### Integration

- Local DHE Connect setup through Home Assistant UI config flow with manual
  host entry, opt-in subnet scan and Zeroconf/mDNS discovery where the network
  exposes `_ste-dhe._tcp.local.` advertisements.
- On-device pairing with per-config-entry token storage, duplicate target
  handling, MAC-based device identity when the device reports it, explicit
  repair pairing and Home Assistant reauthentication for rejected stored tokens.
- Local Socket.IO / Engine.IO v3 runtime with polling setup, authenticated
  WebSocket upgrade, browser-style heartbeat handling, reconnect supervision,
  grace-period availability handling and diagnostic reconnect state.
- Climate control for water heating and target temperature, including support
  for the physical `Tmax` jumper limit, active child-safety limit and DHE
  water-heating on/off fallback.
- Controls and entities for bath fill, eco mode, eco flow limit, child safety,
  wellness programs, brush timer, shower timer, temperature memory slots,
  weather favorites and radio favorites.
- Default-enabled live sensors for current water flow, current power, total
  water consumption and total energy consumption, with recorder-friendly state
  deduplication for high-frequency and diagnostic values.
- Disabled-by-default diagnostic and advanced entities for ODB totals, savings,
  last usage, timer internals, product/device information and protocol state.

### Reliability

- Startup reachability check raises `ConfigEntryNotReady` before platform setup
  if the configured DHE endpoint is not reachable.
- Stored-token authentication failures mark the runtime as `auth_failed` and
  trigger Home Assistant reauthentication instead of silently looping.
- Pending reconnect-grace tasks are cancelled on stop/unload so runtime tasks do
  not outlive their config entry.
- Stale WebSocket receive loops are detected through Engine.IO heartbeat timing
  and enter reconnect instead of leaving entities incorrectly marked connected.
- Timer startup and reconnect readbacks use the same parser as runtime updates,
  so timer switches, duration numbers and reset buttons recover without a Home
  Assistant restart.
- DHE-backed service/action failures are surfaced as Home Assistant errors while
  preserving the original `DHEError` as the exception cause.

### Diagnostics And Security

- Diagnostics exports are anonymized and cover loaded/unloaded runtime state,
  discovery-cache health, reconnect-supervisor state, parser statistics, device
  summary, protocol version source and redacted transport details.
- Hosts, IP addresses, MAC addresses, token paths, token values and local URLs
  are redacted or reduced to presence flags in diagnostics, logs, smoke output,
  PR text and release validation.
- Legal and asset hygiene is documented in `docs/legal.md`; release checks
  reject common secret patterns, generated artifacts, proprietary DHE web assets
  and known proprietary license/copyright markers.
- User-facing branding is reduced to `DHE Connect (Unofficial)` and
  compatibility references are kept neutral in normal documentation.

### Documentation

- README covers installation, removal, setup choices, pairing, reconnect
  behavior, optional dashboard card, troubleshooting entry points and legal
  notes.
- `docs/entities.md` documents entities, attributes and service examples.
- `docs/troubleshooting.md` covers Zeroconf, setup scan, offline/reconnect,
  token/pairing, live sensors, recorder behavior, radio and weather.
- `docs/protocol.md` records observed local interoperability behavior, ODB IDs
  and runtime payload shapes without bundling vendor web assets or code.
- `docs/validation.md` documents the exact Silver-oriented validation command
  set, coverage scope, HA-Test smoke checks and release gates.
- `docs/firmware_matrix.md` starts the tested-device and firmware matrix.

### Validation

- `python scripts/check_coverage.py`: `565 passed`, scoped Silver coverage
  `96%` with documented exclusions for Home Assistant glue and transport paths.
- `python scripts/check_integration.py`: `523` unittest checks plus repository
  guards for manifest/HACS metadata, translations, pinned GitHub Actions,
  `quality_scale.yaml`, generated artifacts, docs links, Python syntax and
  `client.py` size.
- `python scripts/check_typing.py`: no issues in `66` source files.
- `python -m ruff check custom_components/stiebel_dhe_connect tests scripts`:
  passed.
- `python scripts/release_check.py --run-local-checks`: passed with version,
  changelog, documentation, secret/legal scan and local validation gates.
- HA-Test live validation covered install, restart, connected runtime, recorder
  smoke, offline/online reconnect and timer availability recovery.
