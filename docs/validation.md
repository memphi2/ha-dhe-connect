# Validation And Release Checks

This document defines the active validation gate for this repository.

It is version-neutral by design and should not include stale snapshots from
older branches.

For normal installation and updates, use [installation.md](installation.md).
The commands here are development/release checks, not a user setup requirement.

## LTS Compatibility Matrix

The normal pytest suite includes `tests/test_00_recorder_runtime.py`, which
starts the real HA recorder against a temporary SQLite database. It checks idle
deduplication, jitter flushes, zero crossings, live catalog updates with excluded
payloads, and optional countdown writes. No user database or physical DHE is
accessed. These regression checks complement, but do not replace, live database
growth measurements.

Discovery observations update the bounded in-memory cache immediately. Disk
writes are coalesced over a five-second window with one pending timer/write;
regular HA shutdown flushes the latest dirty snapshot. A failed write is retried
on a later observation or shutdown, not in an idle retry loop. An abrupt process
exit can lose the last discovery observations, but not pairing credentials or
config entries; the discovery cache is only a temporary setup aid.

Real HA fixture tests are split into connection, discovery, repairs, runtime and
services modules (`tests/test_00_ha_fixture_*.py`). Shared HA setup lives in
`tests/ha_test_support.py`; stub-compatible client loading lives in
`tests/client_test_support.py`. Client regressions are grouped into catalogs,
commands, sessions and telemetry. Keep helpers in support modules rather than
importing them from a test collection module. The `test_00_` prefix keeps real HA
fixture tests ahead of tests that temporarily load stub-backed modules.

| Surface | Current release gate |
|---|---|
| Minimum supported Home Assistant version | `2026.10.4` |
| Baseline Home Assistant fixture | `requirements-ha.txt` (core and matching test helpers) |
| Minimum-version fixture | `requirements-ha-202610.txt` (core and matching legacy test helpers) |
| Home Assistant drift check | Monthly scheduled and manual latest-HA validation |
| Python validation runtime | `3.14` |
| Runtime dependency baseline | Supplied by the pinned Home Assistant core |
| Marketplace metadata | `hacs.json` declares `homeassistant: 2026.10.4` |
| Catalog category | `climate.water_heaters` in the integration manifest |

The catalog category follows the physical device's purpose, not its entity
platforms. It uses the official
[water-heater category](https://contributors.home-assistant.io/core/integrations/categories/#climate)
for Marketplace discovery; it does not change HA entity domains. `hacs.json`
and the CI check named `HACS` remain correct technical names for the shared
catalog format and validator.

## Dependency Maintenance

Routine Dependabot version updates run quarterly for GitHub Actions and Python,
with one grouped PR per ecosystem and at most one open version-update PR per
ecosystem. Python major updates remain manual compatibility work. The monthly
latest-HA drift check remains enabled; it validates compatibility without
opening dependency-update PRs.

Dependabot security alerts and automatic security-update PRs must stay enabled
in the repository settings. Security updates are reviewed promptly, independently
of the quarterly schedule and version-update PR limit; they are not automatically
merged. See the [Dependabot options reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference).
The repository must receive the configuration on its default branch before the
new version-update schedule takes effect.

Dependabot may raise stable mypy and Ruff minimums inside the reviewed ranges
(`>=2.4,<3` and `>=0.17,<0.18`). The guard parses requirements semantically;
lowered/missing/widened bounds, conditional requirements and prerelease bounds
still fail. Core and its matching test helpers move together in the central
baseline, rather than as independent tool updates.

`requirements.txt` includes only `requirements-ha.txt` and `requirements-tools.txt`.
The shared tools file admits only `mypy`, `ruff` and `pytest-cov`. CI rejects
additional direct dependencies, extra requirement/constraint includes and
duplicated entries. Each HA file contains only core and its matching test
helpers. Runtime dependencies and pytest remain supplied by that pair rather
than independently maintained.

## Marketplace Branding

The catalog and integration display name is `Stiebel Eltron DHE Connect`.
The integration domain remains `stiebel_dhe_connect`; existing config entries,
device identifiers, entity unique IDs and user-assigned names are unchanged.
Device information includes the manufacturer `Stiebel Eltron`, both on setup
and when runtime model/firmware metadata updates an existing device.

The bundled original project artwork uses `brand/icon.png` (256 x 256) and
`brand/icon@2x.png` (512 x 512). The same square artwork serves as the logo via
Home Assistant's supported local fallback, including dark-theme requests.
No vendor logo, remote logo URL, alternate integration domain or runtime image
downloader is introduced. See the
[official brand image rules](https://contributors.home-assistant.io/core/integrations/brands/).

## 2026.11 Release Readiness

HA 2026.10.4 remains supported. Until the final HA 2026.11 release is published,
`requirements-ha.txt` pins an available preview and the official test helpers
from the same core revision. This is preparation, not stable-release validation.

When 2026.11 is released, update only the two pins in `requirements-ha.txt` to
the stable version and its matching core commit. Install `requirements.txt` in
a clean environment, run `python -m pip check` and the full command set below.
Do not publish v2.0.10 until that stable baseline passes. No API, minimum-version,
translation or workflow changes should be needed solely to replace the preview.

Do not duplicate HA's runtime pins in repository requirements or guards:
`aiohttp`, `probatio` and `zeroconf` are installed transitively by core. This keeps
their versions aligned when the central baseline changes.

`scripts/ha_baseline.py` verifies the installed HA version and the test helpers'
VCS origin and commit (or the legacy helper version and its core requirement)
against the chosen requirements file. The drift job
resolves core and helpers from the same release tag into a temporary file, then
installs and verifies both. Stable releases are preferred; while preparing an
unreleased baseline, only previews of that same series are eligible. It never
downgrades to the preceding stable HA series or edits the pinned baseline.

The publication gate additionally rejects prereleases and checks that the
helper commit matches the stable core release tag on GitHub. The matching GitHub
release must also be published, neither a draft nor a prerelease; a tag alone
does not unlock publication. Unavailable metadata or a mismatched installed
environment fails the gate, rather than accepting the requirement text as
evidence of a tested release.

HA 2026.11 uses native climate temperatures, in-place entity ID changes and
exception-based config-entry setup/unload. A small compatibility adapter exposes
the same temperatures on HA 2026.10, preserves its boolean setup/unload results
and cleans up Repairs when an entry is removed. Both versions test unit
conversion and callback cleanup; device metadata works with either DeviceInfo API.

## Release Validation Command Set

All CI test jobs run `scripts/check_coverage.py`. It runs the full pytest suite
once and enforces two line-coverage gates: **85% across every integration module**
and **95% for the scoped deterministic modules**. The 95% figure is not whole-repo
coverage. `EXCLUDED_COVERAGE_FILES` in `scripts/check_coverage.py` lists every
file omitted from the narrower gate and its reason; none are omitted from the
whole-integration gate. Both reports are printed even if one threshold fails.
`scripts/check_integration.py` runs repository guards only; it does not repeat
the tests through a second unittest discovery run.

Run this before opening/finalizing release-prep PRs:

```bash
python -m pip check
python scripts/ha_baseline.py
python scripts/check_coverage.py
python scripts/check_integration.py
python scripts/check_translation_keys.py
python scripts/check_release_consistency.py
python scripts/check_deprecations.py
python scripts/check_privacy_markers.py
python scripts/check_typing.py
python -m ruff check custom_components/stiebel_dhe_connect tests scripts
python scripts/release_check.py --run-local-checks --expect-tag absent --expect-github-release absent
```

For intentional in-progress worktrees:

```bash
python scripts/release_check.py --run-local-checks --allow-dirty --expect-tag skip --expect-github-release skip
```

For the minimum-version checks, use a separate Python 3.14 environment:

```bash
python -m pip install -r requirements-ha-202610.txt -r requirements-tools.txt
python -m pip check
python scripts/ha_baseline.py --requirements requirements-ha-202610.txt
python scripts/check_coverage.py
python scripts/check_typing.py
```

CI runs these checks on every PR update and pushes to `main` or `v*` release
tags, along with the repository guards and the longer loopback soak below.
Working branches without a PR use manual dispatch or the local commands above.
New PR updates cancel obsolete runs for that PR without cancelling main, tag,
scheduled or manually dispatched runs. The compatibility path does not need removal
when HA 2026.11 is released.

## Loopback Runtime Soak

The regular pytest suite includes a short soak using real HA entity platforms
and the real DHE HTTP/WebSocket client against a local fake device. Two warmup
cycles precede measurements of three setup/unload cycles. A separate phase
reconnects the same live client repeatedly, without unloading or replacing it,
with two reconnect warmups followed by the requested number of samples. Idle
sampling follows on that same client. Executor and import work use HA's real
worker threads. No physical device or running HA installation is accessed.

For a longer isolated run with numeric, credential-free evidence:

```bash
python scripts/check_runtime_soak.py --cycles 30 --idle-seconds 60 --json-output /tmp/dhe-soak.json
```

The report records pending tasks, scheduled timer handles, callback counts,
weak references to unloaded clients, traced allocations attributed to the
integration, total traced allocations, and current RSS where `/proc` is
available. Fake-server packet histories are cleared before sampling. The gate
compares equal lifecycle phases after warmup: callbacks and integration task
counts must not grow; total tasks/timers allow two transient entries. Unload
must leave no integration tasks, callbacks or retained clients. Memory growth
limits are 512 KiB integration allocations, 8 MiB total traced allocations and
32 MiB RSS. These deliberately bounded regression checks do not prove that a
real device/firmware remains leak-free over days. Longer idle windows can be
requested with `--idle-seconds`.

The monthly/manual latest-HA job also runs the longer isolated command above
(without keeping a JSON artifact); its numeric summary is written to the job log.

## Optional Live/Lab Gates

These checks depend on local infrastructure and are not universal CI gates.

### Real Zeroconf Smoke

```bash
python scripts/zeroconf_smoke.py --timeout 20
```

### Mounted Home Assistant Smoke

These commands inspect a mounted test configuration and recorder evidence.
They do not install or activate an integration. Verify the intended share and
keep its files and raw output private. Installing code, restarting Home
Assistant and calling live APIs are separate operations.

```bash
python scripts/ha_test_smoke.py --config /mnt/ha-test-config --include-fault-log
```

Recorder observation window:

```bash
python scripts/ha_test_smoke.py --config /mnt/ha-test-config --include-fault-log --monitor-seconds 90
```

Strict idle recorder gate:

```bash
python scripts/ha_test_smoke.py --config /mnt/ha-test-config --include-fault-log --monitor-seconds 600 --require-idle --print-operational-signals
```

For a sanitized evidence file, append `--evidence-json /tmp/dhe-smoke-evidence.json`.
Compare separate idle and water-use windows. Water flow or a completed-use
signal makes a window operational; `--require-idle` rejects such a window
rather than reporting it as idle memory/database evidence.

### Live HA API Smoke

```bash
HA_TEST_URL=http://homeassistant.local:8123 \
HA_TEST_USERNAME=your-ha-user \
HA_TEST_PASSWORD=your-ha-password \
python scripts/ha_test_api.py --config /mnt/ha-test-config --cleanup-localhost-tokens
```

Optional:

- `--entity-smoke`
- `--service-smoke`
- `--timer-smoke`

Use active service smokes only with explicit lab authorization. They can change
heating and radio state; never run them while someone depends on hot water.
Loopback tests are not authorization to access a running HA installation.

## Quality Scale Evidence

The source of truth is:

- `custom_components/stiebel_dhe_connect/quality_scale.yaml`

Repository checks ensure required Silver and Gold-core items stay consistent.

## Gold Evidence Log Template

Use this template for manual live evidence:

```text
Date: YYYY-MM-DD
Branch/tag: vX.Y.Z
Device family: ...
Firmware/web-app version: ...
Test scope:
- Setup/pairing
- Reconfigure
- Repairs
- Reconnect/offline recovery
- Live sensors (water/power)
- Timers
- Optional features (radio/weather/savings)
Result summary:
- Pass/partial with concise notes
Open deviations:
- ...
Privacy check:
- No private host/token/MAC/serial data recorded
```

## Icon Translation Status

`icon-translations` remains `exempt` for this integration because the entity
surface uses static icon assignments and does not use translatable dynamic icon
metadata.

If dynamic icon variants are introduced later, this exemption must be rechecked.

## Release Readiness

Before publication:

```bash
python scripts/release_check.py --run-local-checks --run-github-hygiene --expect-tag absent --expect-github-release absent
```

After publication:

```bash
python scripts/release_check.py --expect-tag present --expect-github-release present --require-current-tag
```

The published-release check rejects drafts, prereleases and mismatched tag names.
It resolves the tag directly through the GitHub API, including annotated tags,
and requires its commit to match local HEAD. A matching local tag alone is not
proof that the same commit was published.

## Security Hygiene

- Do not publish tokens, private hosts, private IPs or credentials.
- Treat mounted HA config directories as sensitive.
- Prefer sanitized helper output over raw `.storage` dumps.
