# Changelog

## Unreleased

- Switched the README release badge to tag-based semver sorting so the shown
  release no longer sticks to an outdated older version.
- Refactored Zeroconf discovery conflict abort handling in `config_flow.py`
  into a shared helper to reduce duplicated conflict-path logic.
- Refactored weather service handlers in `__init__.py` to use one shared
  location-resolution helper for add/toggle/remove/select actions.
- Refactored subnet-scan value steps in `config_flow.py` to use one shared
  CIDR/network-mask input helper while keeping behavior unchanged.
- Added a compatibility fallback test for translated Home Assistant action
  errors when translation kwargs are not supported by the exception signature.
- Added `docs/platinum_prep.md` and linked it from README/validation docs to
  track the remaining strict-typing path toward Platinum readiness.
- Hardened the typing gate by enabling mypy `warn_return_any` and
  `warn_unused_ignores`, and fixed the resulting no-any-return issues across
  setup, diagnostics, transport and service helper paths.
- Added the first `disallow_untyped_defs` module group gate (helpers,
  connectivity, diagnostics and pairing-validation utilities) as a controlled
  step toward Platinum strict typing.

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
