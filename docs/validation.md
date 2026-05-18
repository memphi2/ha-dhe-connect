# Validation And Release Checks

This document collects the checks used before merging release-prep or hardening
work. The commands below do not publish a Git tag or GitHub release by
themselves.

## Local Checks

Run the full local gate before opening a pull request:

```bash
python -m pytest -q
python scripts/check_integration.py
python scripts/check_typing.py
python -m ruff check custom_components/stiebel_dhe_connect tests scripts
```

What those checks cover:

- Unit and behavior tests, including fake DHE Engine.IO tests.
- Home Assistant fixture runtime tests for setup, reload, unload and multi-entry
  behavior.
- Repository consistency, required files, translations, pinned validation
  actions, Python syntax and `client.py` size.
- Static type checks for the scoped integration, config/options flow, platform,
  command, runtime, transport and helper modules.
- Ruff linting for integration code, tests and repository scripts.

The GitHub `Validate` workflow runs HACS, Hassfest, pytest, repository checks,
type checks and Ruff. Keep local results and CI results aligned before merging.

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
- Command readback confirmation for setpoint and water-heating writes.
- Command-level temperature-memory generation/readback.
- Radio favorite add and station selection readback.
- Weather favorite add/remove and selected-location readback.

Sanitized protocol replay fixtures in `tests/fixtures/` are synthetic JSON
frames that exercise parser and runtime handling without storing live DHE
captures, hosts, credentials or device identifiers.

The Home Assistant fixture tests exercise the integration through real HA config
entry setup paths instead of only isolated stubs:

- Setup and unload.
- Config-flow setup pairing entry creation.
- Config-flow duplicate-target rejection.
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

These tests are not a replacement for live hardware checks, but they catch
regressions that pure helper tests cannot see.

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

## Release Readiness

Before publishing a release, run:

```bash
python scripts/release_check.py --run-local-checks --ha-config /mnt/ha-test-config --ha-monitor-seconds 90
```

Before publication, the default expectation is:

- Version is present in `manifest.json`, README and CHANGELOG.
- Git worktree is clean.
- Whitespace and tracked-file secret scans pass.
- The release tag is absent.
- The GitHub release is absent.
- Local checks pass.
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
