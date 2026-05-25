# DHE Connect for Home Assistant (Unofficial)

[![Validate](https://github.com/memphi2/ha-dhe-connect/actions/workflows/validate.yml/badge.svg)](https://github.com/memphi2/ha-dhe-connect/actions/workflows/validate.yml)
[![Quality](https://img.shields.io/badge/Quality-HA%20QS%20Platinum%20Track-0366d6?style=flat-square)](custom_components/stiebel_dhe_connect/quality_scale.yaml)
[![GitHub Release](https://img.shields.io/github/v/tag/memphi2/ha-dhe-connect?sort=semver&label=release)](https://github.com/memphi2/ha-dhe-connect/releases)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://www.hacs.xyz/)
[![License MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Unofficial local Home Assistant integration for compatible DHE Connect
instantaneous water heaters.

The integration uses the local DHE web interface only (no cloud relay).

<img src="assets/dhe-connect-card.png" alt="DHE Connect Card dashboard screenshot" width="420">

## Status

- Current version: `2.0.0-beta`
- Current line: v2 beta hardening
- Next milestone: `v2.0.1` documentation/process cleanup
- Quality target: Home Assistant Quality Scale Platinum track for a custom integration
- Not an official Home Assistant Core certification

## Documentation

| Topic | Document |
|---|---|
| Entity list, attributes and service examples | [docs/entities.md](docs/entities.md) |
| Pairing, connectivity and recorder troubleshooting | [docs/troubleshooting.md](docs/troubleshooting.md) |
| Validation and release gates | [docs/validation.md](docs/validation.md) |
| Automation examples | [docs/examples.md](docs/examples.md) |
| Practical use cases | [docs/use-cases.md](docs/use-cases.md) |
| Known limitations | [docs/known_limitations.md](docs/known_limitations.md) |
| Device and firmware evidence matrix | [docs/firmware_matrix.md](docs/firmware_matrix.md) |
| Protocol and ODB reference | [docs/protocol.md](docs/protocol.md) |
| Migration policy (v2 line) | [docs/migration_policy.md](docs/migration_policy.md) |
| Release process checklist | [docs/release_process.md](docs/release_process.md) |
| FAQ | [docs/faq.md](docs/faq.md) |
| German quick guide | [docs/de.md](docs/de.md) |
| Legal and asset hygiene | [docs/legal.md](docs/legal.md) |
| Security and token handling | [SECURITY.md](SECURITY.md) |

## Installation

### HACS custom repository

1. Open HACS.
2. Go to `Integrations`.
3. Open `Custom repositories`.
4. Add:

   ```text
   https://github.com/memphi2/ha-dhe-connect
   ```

5. Category: `Integration`.
6. Install `DHE Connect`.
7. Restart Home Assistant.
8. Add from `Settings` -> `Devices & services`.

### Manual installation

Copy to:

```text
/config/custom_components/stiebel_dhe_connect/
```

Restart Home Assistant and add `DHE Connect` from the UI.

### Removal

1. Open `Settings` -> `Devices & services`.
2. Open the `DHE Connect` integration entry.
3. Use the three-dot menu -> `Delete`.
4. For manual installs, remove `/config/custom_components/stiebel_dhe_connect/` after the entry is removed.

## Setup

The setup flow supports:

- Zeroconf discovery (`_ste-dhe._tcp.local.`)
- Subnet scan (private IPv4 ranges, default port `8443`)
- Manual host/port entry

Zeroconf typically works only in the local subnet/VLAN unless mDNS relay is
configured.

Each DHE uses its own config entry and token file:

```text
/config/.storage/stiebel_dhe_connect_token_<host>_<port>.txt
```

## Core behavior

- Local push runtime via Socket.IO / Engine.IO.
- Climate control, timers, eco mode, bath fill, child safety, wellness,
  radio, weather.
- Recorder-sensitive and diagnostic entities are disabled by default where
  appropriate.

For full details, use [docs/entities.md](docs/entities.md) and
[docs/protocol.md](docs/protocol.md).

## Validation

Install local dependencies once:

```bash
python -m pip install -r requirements.txt
```

Run the standard gate:

```bash
python scripts/check_coverage.py
python scripts/check_integration.py
python scripts/check_deprecations.py
python scripts/check_typing.py
python -m ruff check custom_components/stiebel_dhe_connect tests scripts
python scripts/release_check.py --run-local-checks --expect-tag absent --expect-github-release absent
```

For full gate details and optional live smoke tests, see
[docs/validation.md](docs/validation.md).

## Security notes

- Use only on trusted local networks.
- Do not expose the DHE web interface to the internet.
- Treat Home Assistant backups/config mounts as sensitive.
- Do not publish tokens, private hosts or private IPs.

See [SECURITY.md](SECURITY.md) and [docs/legal.md](docs/legal.md).
