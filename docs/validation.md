# Validation And Release Checks

This document defines the active validation gate for this repository.

It is version-neutral by design and should not include stale snapshots from
older branches.

## Release Validation Command Set

Run this before opening/finalizing release-prep PRs:

```bash
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
