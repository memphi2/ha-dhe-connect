# Stiebel DHE Connect

Home Assistant custom integration for Stiebel Eltron DHE Connect instantaneous water heaters.

This component uses the local DHE Socket.IO / Engine.IO v3 long-polling interface. It is designed for trusted local networks and does not use a cloud service.

## Version

Current version: `0.7.3`.

## Entities

The integration provides:

- target-temperature climate control
- current water flow, current power and configured power sensors
- water and energy consumption sensors from DHE app chart messages
- Eco mode, Eco flow limit and maximum-temperature controls
- bath-fill switch and target-volume control
- brush timer and shower timer switches, duration numbers, remaining sensors and reset buttons

Bath fill and timer switches start and stop the respective function. Timer durations are limited to `20 min`. Timer remaining sensors are displayed as `M:SS`.

## Installation

Install through HACS as a custom repository:

```text
https://github.com/memphi2/ha-dhe-connect
```

Category: `Integration`.

After installation, restart Home Assistant and add `Stiebel DHE Connect` from `Settings` -> `Devices & services`.

## Configuration

Required values:

| Field | Example |
|---|---|
| IP address or hostname | `172.16.2.124` |
| Port | `8443` |
| Device name | `DHE Connect` |

On first connection the DHE may request pairing. Confirm pairing on the DHE when prompted.

## Token

The local pairing token is stored at:

```text
/config/.storage/stiebel_dhe_connect_token.txt
```

Delete this file to force a new pairing.

## Documentation

See the repository root [`README.md`](../../README.md) for full entity, protocol, troubleshooting and security notes.
