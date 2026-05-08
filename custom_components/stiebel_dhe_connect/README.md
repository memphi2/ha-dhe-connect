# Stiebel DHE Connect

Home Assistant custom integration for Stiebel Eltron DHE Connect instantaneous water heaters.

This component uses the local DHE Socket.IO / Engine.IO v3 interface, authenticates through polling and then upgrades to the same WebSocket transport used by the DHE web UI. It is designed for trusted local networks and does not use a cloud service.

## Version

Current version: `0.8.0` (WebSocket protocol alignment and diagnostics).

## Entities

The integration provides:

- target-temperature climate control
- best-effort startup reads for all currently known DHE web UI values
- current water flow, current power and configured power sensors
- water, energy, last usage and saving monitor sensors from DHE app messages
- diagnostic online status and reconnect count entities
- diagnostic device info and unhandled ODB value entities
- Eco mode, Eco flow limit and maximum-temperature controls
- bath-fill switch and target-volume control
- brush timer and shower timer switches, duration numbers, remaining sensors and reset buttons
- temperature memory preset buttons for DHE memory slots 1 and 2
- box-style number inputs for temperature memory values and timer durations
- wellness cold prevention switch and wellness program switches (winter refresh, summer fitness, circulation support)

Bath fill and timer switches start and stop the respective function. Timer durations are limited to `20 min` and are shown as box inputs. Timer remaining sensors are displayed as `M:SS`. Temperature memory values are configurable through box inputs.

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
| IP address or hostname | `192.168.1.100` |
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
