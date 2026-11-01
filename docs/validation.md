# Validation And Release Checks

This document defines the active validation gate for this repository.

It is version-neutral by design and should not include stale snapshots from
older branches.

## LTS Compatibility Matrix

| Surface | Current release gate |
|---|---|
| Minimum supported Home Assistant version | `2026.11.0` |
| Baseline Home Assistant fixture | `requirements-ha.txt` (core and matching test helpers) |
| Home Assistant drift check | Monthly scheduled and manual latest-HA validation |
| Python validation runtime | `3.14` |
| Runtime dependency baseline | Supplied by the pinned Home Assistant core |
| HACS metadata | `hacs.json` declares `homeassistant: 2026.11.0` |

## 2026.11 Release Readiness

The minimum targets the final release, not a preview. Until it is published,
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
VCS origin and commit against the chosen requirements file. The drift job
resolves core and helpers from the same release tag into a temporary file, then
installs and verifies both. Stable releases are preferred; while preparing an
unreleased baseline, only previews of that same series are eligible. It never
downgrades to the preceding stable HA series or edits the pinned baseline.

The publication gate additionally rejects prereleases and checks that the
helper commit matches the stable core release tag on GitHub. An unavailable
tag or mismatched installed environment fails the gate, rather than accepting
the requirement text as evidence of a tested release.

Temperature state uses the native climate API. Entity ID changes retain DHE
callbacks in place. Config-entry setup/unload succeed with `None` and raise a
config-entry exception on failure. Device metadata uses the 2026.11 `DeviceInfo`
dataclass. Older HA versions require v2.0.9.

## Release Validation Command Set

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

## Optional Live/Lab Gates

These checks depend on local infrastructure and are not universal CI gates.

### Real Zeroconf Smoke

```bash
python scripts/zeroconf_smoke.py --timeout 20
```

### Mounted Home Assistant Smoke

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

Use active service smokes only when live control changes are acceptable.

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

## Security Hygiene

- Do not publish tokens, private hosts, private IPs or credentials.
- Treat mounted HA config directories as sensitive.
- Prefer sanitized helper output over raw `.storage` dumps.
