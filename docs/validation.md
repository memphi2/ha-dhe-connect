# Validation And Release Checks

This document collects the checks used before merging release-prep or hardening
work. The commands below do not publish a Git tag or GitHub release by
themselves.

## Silver Validation Command Set

Run the Silver-oriented gate before opening a pull request or release-prep
commit:

```bash
python scripts/check_coverage.py
python scripts/check_integration.py
python scripts/check_typing.py
python -m ruff check custom_components/stiebel_dhe_connect tests scripts
python scripts/release_check.py --run-local-checks
```

What those checks cover:

- Unit and behavior tests with pytest-cov line coverage for
  `custom_components/stiebel_dhe_connect`.
- The Silver coverage gate requires at least 95% line coverage for deterministic
  integration modules.
- `custom_components/stiebel_dhe_connect/quality_scale.yaml` tracks all Home
  Assistant Bronze and Silver rules as `done`; repository checks fail if one of
  those rule IDs is missing or downgraded.
- Fake DHE Engine.IO tests.
- Config-entry diagnostics tests for loaded and unloaded clients, anonymized
  host/IP/MAC/token fields, sanitized diagnostic state and preserved cache
  counts/key lists.
- Home Assistant fixture runtime tests for setup, reload, unload and multi-entry
  behavior.
- Repository consistency, required files, translations, pinned validation
  actions, Python syntax and `client.py` size.
- Static type checks for the scoped integration, config/options flow, platform,
  command, runtime, transport and helper modules.
- Ruff linting for integration code, tests and repository scripts.
- Release-readiness checks for version consistency, empty `Unreleased`
  changelog state, tracked-file secret hygiene, generated-artifact hygiene,
  local validation commands and optional lab smoke gates.

This validation set is maintained for this custom repository. It is intended to
match the Home Assistant Quality Scale Silver expectations that apply to the
integration, but it is not an official Home Assistant core certification.

During active development, when the tree is intentionally dirty, use the same
release check with `--allow-dirty --expect-tag skip --expect-github-release
skip`. The final release gate should run without `--allow-dirty`.

The GitHub `Validate` workflow runs HACS, Hassfest, pytest, repository checks,
type checks and Ruff. Keep local results and CI results aligned before merging.

## Silver Coverage Gate

`scripts/check_coverage.py` runs the full pytest suite through pytest-cov and
then reports coverage for deterministic parser, mapping, diagnostics and state
helper modules. The gate intentionally excludes Home Assistant setup/platform
glue and live DHE transport/command orchestration from the 95% line-coverage
threshold. Those paths remain covered by HA fixture tests, Fake-DHE tests and
the live smoke gates below; they are excluded only from the strict line metric
because their executed branches depend on Home Assistant callback timing,
network transport state or firmware-specific device payloads.

The remaining coverage interpretation risk is strictness: if Silver is read as
"95% over every physical integration line, including Home Assistant and
transport glue", this repository is intentionally stricter on deterministic
modules and verifies the glue paths through fixture, Fake-DHE and live smoke
gates instead. The documented Silver gate currently reports 96% with the
exclusions below.

Current exclusions from the 95% line-coverage report:

- `custom_components/stiebel_dhe_connect/__init__.py` - Home Assistant setup,
  service registration and config-entry glue.
- `custom_components/stiebel_dhe_connect/binary_sensor.py` - Home Assistant
  platform entity glue.
- `custom_components/stiebel_dhe_connect/button.py` - Home Assistant platform
  entity glue.
- `custom_components/stiebel_dhe_connect/climate.py` - Home Assistant platform
  entity glue.
- `custom_components/stiebel_dhe_connect/media_player.py` - Home Assistant
  platform entity glue.
- `custom_components/stiebel_dhe_connect/number.py` - Home Assistant platform
  entity glue.
- `custom_components/stiebel_dhe_connect/select.py` - Home Assistant platform
  entity glue.
- `custom_components/stiebel_dhe_connect/sensor.py` - Home Assistant platform
  entity glue.
- `custom_components/stiebel_dhe_connect/switch.py` - Home Assistant platform
  entity glue.
- `custom_components/stiebel_dhe_connect/text.py` - Home Assistant platform
  entity glue.
- `custom_components/stiebel_dhe_connect/client.py` - long-running client
  lifecycle glue covered by Fake-DHE and HA fixtures.
- `custom_components/stiebel_dhe_connect/client_callbacks.py` - callback
  registration glue covered through platform fixture tests.
- `custom_components/stiebel_dhe_connect/client_command_runner.py` - command
  transport orchestration covered by Fake-DHE flow tests.
- `custom_components/stiebel_dhe_connect/client_commands.py` - DHE command
  wrappers covered by Fake-DHE and live smoke gates.
- `custom_components/stiebel_dhe_connect/client_connection_state.py` -
  reconnect availability glue covered by focused supervisor tests.
- `custom_components/stiebel_dhe_connect/client_device_info_commands.py` - DHE
  command wrappers covered by Fake-DHE and diagnostics tests.
- `custom_components/stiebel_dhe_connect/client_pairing.py` - pairing protocol
  orchestration covered by Fake-DHE setup tests.
- `custom_components/stiebel_dhe_connect/client_radio_commands.py` - DHE radio
  command wrappers covered by Fake-DHE and smoke tests.
- `custom_components/stiebel_dhe_connect/client_runtime.py` - runtime parser
  dispatcher with firmware-dependent edge branches.
- `custom_components/stiebel_dhe_connect/client_runtime_app.py` - runtime app
  payload dispatcher with firmware-dependent edge branches.
- `custom_components/stiebel_dhe_connect/client_runtime_media.py` - runtime
  radio/weather dispatcher with firmware-dependent edge branches.
- `custom_components/stiebel_dhe_connect/client_temperature_memory_commands.py` -
  DHE temperature-memory command wrappers covered by Fake-DHE tests.
- `custom_components/stiebel_dhe_connect/client_transport.py` - Engine.IO
  transport glue covered by Fake-DHE and live smoke gates.
- `custom_components/stiebel_dhe_connect/client_transport_auth.py` - Engine.IO
  authentication and pairing transport glue.
- `custom_components/stiebel_dhe_connect/client_transport_helpers.py` -
  Engine.IO transport helper edge handling covered by transport tests.
- `custom_components/stiebel_dhe_connect/client_weather_commands.py` - DHE
  weather command wrappers covered by Fake-DHE and service tests.
- `custom_components/stiebel_dhe_connect/client_web_version.py` - DHE
  web-interface version fetch glue covered by live/Fake-DHE paths.
- `custom_components/stiebel_dhe_connect/client_wellness_timer_commands.py` -
  DHE wellness/timer command wrappers covered by Fake-DHE tests.
- `custom_components/stiebel_dhe_connect/config_flow.py` - Home Assistant
  config-flow orchestration glue covered by HA fixtures.
- `custom_components/stiebel_dhe_connect/config_flow_discovery.py` - Home
  Assistant discovery-flow glue covered by HA fixtures.
- `custom_components/stiebel_dhe_connect/config_flow_mapping.py` - options-flow
  selector glue covered by flow helper tests.
- `custom_components/stiebel_dhe_connect/config_flow_schemas.py` - Home
  Assistant voluptuous schema glue covered by flow tests.
- `custom_components/stiebel_dhe_connect/config_flow_setup.py` - Home Assistant
  setup-form glue covered by HA fixtures.
- `custom_components/stiebel_dhe_connect/discovery_state.py` - discovery cache
  persistence glue covered by dedicated discovery tests.
- `custom_components/stiebel_dhe_connect/engineio_helpers.py` - Engine.IO parser
  edge glue covered by transport tests.
- `custom_components/stiebel_dhe_connect/pairing_helpers.py` - pairing
  file-name normalization glue covered by pairing tests.
- `custom_components/stiebel_dhe_connect/setup_scan.py` - user-triggered
  network scan I/O glue covered by helper and HA tests.

## Fake DHE And HA Fixture Coverage

The fake DHE Engine.IO test server exercises the local protocol without a
physical heater:

- Engine.IO polling session open.
- Socket.IO namespace open.
- WebSocket probe and upgrade.
- Runtime message parsing.
- Stored-token authentication and setup-pairing confirmation.
- Manual pairing where a token arrives before the final pairing result.
- Rejected pairing and closed-session handling.
- Invalid-token repair pairing against a fresh Fake-DHE pairing round.
- Partial WebSocket shutdown handling after a successful upgrade.
- Malformed runtime payloads, invalid commands and invalid ODB payloads.
- Command readback confirmation for setpoint and water-heating writes.
- Reconnect during command execution followed by command retry on a replacement
  session.
- Delayed explicit readbacks after command writes.
- Command-level temperature-memory generation/readback.
- Timer reset/recovery behavior against app-level runtime readbacks.
- Radio favorite add/remove and station selection readback.
- Weather favorite add/remove, existing-favorite sync and selected-location
  readback.

Sanitized protocol replay fixtures in `tests/fixtures/firmware_*/` are JSON
frames that exercise parser and runtime handling without storing live DHE
captures, hosts, credentials or device identifiers. The current replay profiles
cover setpoint/status/media/weather updates, timer and consumption updates, and
device-info/catalog payloads, including named ODB commands normalized through the
`ODB_DEBUG_NAMES` reverse map. New sanitized captures from real devices should be
added as separate firmware folders with expected runtime-state assertions so
parser regressions are caught across firmware variants.

The Home Assistant fixture tests exercise the integration through real HA config
entry setup paths instead of only isolated stubs:

- Setup and unload.
- Setup reachability failure with `ConfigEntryNotReady` before platforms are
  loaded.
- Domain-level service registration before a config entry is loaded.
- Config-flow setup pairing entry creation.
- Config-entry reauthentication when a stored DHE token is no longer accepted.
- Complete Zeroconf -> Tmax -> setup pairing -> config-entry creation against
  the Fake-DHE Engine.IO server.
- Config-flow duplicate-target rejection.
- Config-flow setup-method selection for Zeroconf discoveries, subnet scan and
  manual entry.
- Config-flow progress-step handling for setup subnet scan with synthetic scan
  results.
- Zeroconf payload variants from realistic mDNS data, including host/hostname
  fallback, `.local.` names, missing-port defaults and invalid-port aborts.
- Discovery identity scoring, temporary cache persistence, repeated-prompt
  suppression, preferred identity source tracking and conflicting identity
  diagnostics.
- Export-only reconnect and transport metrics for support diagnostics, including
  successful reconnect counts, reconnect durations and WebSocket upgrade
  failures without adding recorder-heavy runtime attributes.
- Zeroconf user-takeover flow from an in-progress discovery through Tmax
  selection and pairing confirmation.
- MAC-based duplicate detection after pairing when the same DHE is discovered
  through a different hostname/IP target.
- MAC-based config-entry unique IDs across Zeroconf, scan-prefilled and manual
  setup.
- Options-flow connection target changes with pairing confirmation.
- Reload cleanup and restart behavior.
- Multiple configured DHE entries.
- Multi-entry service routing.
- Service registration lifetime.
- Entity-registry unique-ID separation.
- Entity-registry stability across reload.
- Disabled-by-default repair-pairing button enablement and service press.
- Runtime availability callbacks and recovery.
- Cached weather service candidate resolution.
- Runtime measurement, reconnect and diagnostic sensor callbacks.
- Runtime `auth_failed` diagnostics starting Home Assistant reauthentication
  once.
- Platform `PARALLEL_UPDATES = 0` quality-scale guard coverage.

These tests are not a replacement for live hardware checks, but they catch
regressions that pure helper tests cannot see.

## Real Zeroconf Smoke

Run the real Zeroconf/mDNS smoke from a host and network segment where Home
Assistant should see the DHE multicast DNS-SD advertisement:

```bash
python scripts/zeroconf_smoke.py --timeout 20
```

The smoke listens for `_ste-dhe._tcp.local.` and verifies the service appears on
the expected DHE port, default `8443`. It intentionally does not print private
hostnames, IP addresses or token context. This validates multicast discovery
visibility; it is not a replacement for manual setup or the setup subnet scan.

Treat this as a release-lab gate, not as a universal CI check. It depends on the
current network carrying the DHE mDNS multicast advertisement; VLAN, firewall or
router policies can make this smoke fail even when the integration code is
correct. Keep it opt-in through `--run-zeroconf-smoke`.

If the DHE is in another VLAN, run the smoke from the correct segment or ensure
the router/firewall has an mDNS reflector configured. A direct `.local` lookup
or unicast DNS-SD answer can still work while Home Assistant Zeroconf discovery
does not, because the config flow depends on receiving the multicast
advertisement.

## Mounted Home Assistant Smoke

For a mounted Home Assistant test configuration, run:

```bash
python scripts/ha_test_smoke.py --config /mnt/ha-test-config --include-fault-log
```

The smoke check reads the mounted config directly. It checks entity-registry
state, recorder state, current logs, DHE connection state, reconnect count and
temporary localhost HA tokens. It does not need Home Assistant credentials and
does not print stored DHE tokens.

CI also runs a synthetic mounted-config fixture for this smoke path. That test
builds a minimal entity registry, recorder database and log file, then executes
the same smoke runner including recorder-write monitoring without requiring a
live Home Assistant instance.

To monitor recorder churn, add a time window:

```bash
python scripts/ha_test_smoke.py --config /mnt/ha-test-config --include-fault-log --monitor-seconds 90
```

Run the recorder monitor while the DHE is idle when validating database churn.
If the device-status sensor reports water running (`status_2` or the observed
transition state `status_4`), or if `Last usage duration` changes during the
window, the smoke check treats the window as operational and skips idle
recorder-write limits while still checking logs and reconnect stability.

## Live HA API Smoke

The API helper can log into a test Home Assistant instance, request restart,
wait for it to come back online and optionally run service smoke:

```bash
HA_TEST_URL=http://homeassistant.local:8123 \
HA_TEST_USERNAME=your-ha-user \
HA_TEST_PASSWORD=your-ha-password \
python scripts/ha_test_api.py --config /mnt/ha-test-config --cleanup-localhost-tokens
```

Use `--entity-smoke` for read-only API validation of the core DHE entities. It
checks that the climate, radio, weather, connection, live flow/power and timer
entities are present, available and expose the expected state shape.

Only use `--service-smoke` or `--timer-smoke` when active service calls are
acceptable. `--service-smoke` can call `climate.turn_off`, `climate.turn_on`,
`media_player.turn_off` and `media_player.select_source`. `--timer-smoke`
temporarily changes the brush timer duration, starts/stops the brush timer,
verifies local countdown, rapid restart, stop readback sync and expiry reset,
then restores the original timer duration. If the device-status sensor reports
water running (`status_2` or `status_4`) at the start, `--timer-smoke` skips its
active timer actions.

The helper tries to revoke its temporary refresh token. If Home Assistant
rejects that revoke request, use `--cleanup-localhost-tokens` with the mounted
config so leftover localhost tokens are removed from `.storage/auth`. The
fallback cleanup retries the mounted auth-file cleanup because a running Home
Assistant instance can briefly re-persist token state after a failed revoke. For
authenticated service smoke, the release helper restarts HA before the fallback
cleanup so the mounted auth file is not immediately overwritten by stale runtime
state.

When `--service-smoke` selects a radio source, it turns the radio off again
after 30 seconds by default. Use `--radio-auto-off-seconds` only when a longer
manual listening window is needed.

## Live Offline/Online Reconnect Gate

Before release, run one manual live HA-Test cycle when reconnect behavior or
control availability changed:

1. Start from a connected DHE and verify Home Assistant reports
   `Connection state: connected`.
2. Confirm representative controls are available, especially water heating,
   brush/shower timer switches, timer duration numbers and timer reset buttons.
3. Take the DHE offline without restarting Home Assistant.
4. Verify the DHE TCP port becomes unreachable from the test host.
5. Wait for Home Assistant to move to `Connection state: reconnecting`.
6. After the reconnect grace window expires, verify climate and DHE-backed
   controls become `unavailable`.
7. Bring the DHE back online and wait through the reconnect backoff.
8. Verify Home Assistant returns to `connected`, timer switches return to their
   DHE state and timer duration/reset controls become available again.
9. Run mounted HA smoke with a short recorder monitor and confirm no DHE-related
   log errors and no unexpected recorder churn.

Record this as release-lab evidence only. Do not publish private hostnames, IP
addresses, credentials, token paths or raw diagnostic payloads in release notes,
PR text or documentation.

## Release Readiness

Before publishing a release, run:

```bash
python scripts/release_check.py --run-local-checks --run-zeroconf-smoke --ha-config /mnt/ha-test-config --ha-monitor-seconds 90
```

Before publication, the default expectation is:

- Version is present in `manifest.json`, README and CHANGELOG.
- Git worktree is clean.
- Whitespace and tracked-file secret scans pass.
- The release tag is absent.
- The GitHub release is absent.
- Local checks pass, including the explicit `tests/test_diagnostics.py` gate
  before the full pytest suite.
- The opt-in real Zeroconf/mDNS release-lab smoke gate passes when
  `--run-zeroconf-smoke` is used in a network where mDNS visibility is expected.
- Optional mounted HA smoke passes when `--ha-config` is provided.

After publication, rerun with:

```bash
python scripts/release_check.py --expect-tag present --expect-github-release present --require-current-tag
```

The release-readiness helper validates state. It does not create tags, push
tags, publish GitHub releases or update HACS metadata.

## Security Hygiene

- Do not paste DHE tokens, Home Assistant tokens, private hostnames or local IPs
  into pull request text, release notes or public issues.
- Keep mounted Home Assistant config directories private.
- Remove temporary HA auth backups from `/tmp` after localhost-token cleanup.
- Prefer sanitized helper output over raw `.storage` or log snippets.
