# Changelog

## Unreleased

- Home Assistant and HACS display names now use `DHE Connect`; the repository
  documentation keeps the unofficial community-project disclaimer.

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
