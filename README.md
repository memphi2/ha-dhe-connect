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

- Current version: `2.0.1`
- Release channel: stable
- Quality target: Home Assistant Quality Scale Platinum track for a custom integration
- Support scope: stable tags are supported; private/dev branches are best-effort
- Not an official Home Assistant Core certification

## Highlights

- Local runtime connection (Socket.IO / Engine.IO), no cloud dependency.
- Climate target temperature control with reconnect-aware behavior.
- Live water flow and live power for daily monitoring.
- Timer, eco mode, child safety, bath fill and wellness controls.
- Radio and weather support through the DHE runtime payload.
- Multi-device support: one config entry per DHE.

## Important Entities

Common entities used in dashboards and automations:

- `climate.dhe_connect`
- `sensor.dhe_connect_connection_state`
- `sensor.dhe_connect_current_power`
- `sensor.dhe_connect_current_water_flow`
- `switch.dhe_connect_eco_mode`
- `switch.dhe_connect_bath_fill`

Complete entity reference:
[docs/entities.md](docs/entities.md)

## Quick Automation Example

```yaml
alias: DHE eco mode at night
triggers:
  - trigger: time
    at: "22:30:00"
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.dhe_connect_eco_mode
mode: single
```

More automation examples and practical scenarios:

- [docs/examples.md](docs/examples.md)
- [docs/use-cases.md](docs/use-cases.md)

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

Zeroconf usually requires mDNS visibility in the local subnet/VLAN or an
explicit relay setup across subnets.

Each DHE uses its own token file:

```text
/config/.storage/stiebel_dhe_connect_token_<host>_<port>.txt
```

## Security Notes

- Use only on trusted local networks.
- Do not expose the DHE web interface to the internet.
- Treat Home Assistant backups/config mounts as sensitive.
- Do not publish tokens, private hosts or private IPs.

See [SECURITY.md](SECURITY.md).

## Documentation

| Topic | Document |
|---|---|
| Pairing, connectivity and recorder troubleshooting | [docs/troubleshooting.md](docs/troubleshooting.md) |
| Entity list, attributes and service examples | [docs/entities.md](docs/entities.md) |
| Automation examples | [docs/examples.md](docs/examples.md) |
| Practical use cases | [docs/use-cases.md](docs/use-cases.md) |
| Known limitations | [docs/known_limitations.md](docs/known_limitations.md) |
| Device and firmware evidence matrix | [docs/firmware_matrix.md](docs/firmware_matrix.md) |
| Protocol and ODB reference | [docs/protocol.md](docs/protocol.md) |
| Migration policy (v2 line) | [docs/migration_policy.md](docs/migration_policy.md) |
| Release process checklist | [docs/release_process.md](docs/release_process.md) |
| German quick guide | [docs/de.md](docs/de.md) |
| Legal and asset hygiene | [docs/legal.md](docs/legal.md) |

## Legal Status

This project is an unofficial community integration. It is not affiliated with,
endorsed by, sponsored by or otherwise approved by any device manufacturer,
Home Assistant, HACS or their respective owners.

See [docs/legal.md](docs/legal.md) for full legal and asset-hygiene details.
