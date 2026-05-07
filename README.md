# Stiebel DHE Connect for Home Assistant

Custom Home Assistant integration for Stiebel Eltron DHE Connect instantaneous water heaters.

The integration talks to the local DHE web interface through the device's Socket.IO / Engine.IO v3 long-polling endpoint. It is intended for trusted local networks and does not use a cloud service.

## Status

Experimental custom integration. Tested with a locally reachable DHE Connect on port `8443`.

Current version: `0.7.5`.

## Features

- UI-based Home Assistant config flow.
- Local connection by IP address or hostname.
- Persistent Socket.IO / Engine.IO v3 long-polling session.
- Automatic reconnect if the DHE closes the session.
- Target-temperature control through the existing DHE ODB interface.
- Current water flow, current power, configured power and app consumption sensors.
- Eco mode, Eco flow limit, maximum temperature and bath-fill controls.
- Separate brush timer and shower timer controls.
- Timer reset buttons.
- Wellness cold prevention switch.
- Wellness shower program buttons (winter refresh, summer fitness, circulation support).
- Bath fill and timer start/stop via switches.
- Timer duration numbers limited to `20 min`.
- Timer remaining sensors displayed as `M:SS`.
- English and German Home Assistant translations.
- HACS-compatible repository layout, including brand icons in `brand/`.

## Home Assistant entities

### Climate

| Entity | Source / behavior |
|---|---|
| Displayed target temperature | Read from ODB ID `0`, written through ODB ID `66` |

### Sensors

| Entity | Source / scaling |
|---|---|
| Current water flow | ODB ID `15 / 10`, unit `L/min` |
| Current power consumption | ODB ID `16 / 100 * configured_power_kw`, unit `kW` |
| Configured power | ODB ID `20`, unit `kW` |
| Water consumption week | `set:ste.app.consumption:waterWeek`, unit `L` |
| Water consumption year | `set:ste.app.consumption:waterYear`, unit `m3` |
| Water consumption years | `set:ste.app.consumption:waterYears`, unit `m3` |
| Energy consumption week | `set:ste.app.consumption:energyWeek`, unit `kWh` |
| Energy consumption year | `set:ste.app.consumption:energyYear`, unit `kWh` |
| Energy consumption years | `set:ste.app.consumption:energyYears`, unit `kWh` |
| Brush timer remaining | `set:ste.app.brushTimer:remainingMilliseconds`, displayed as `M:SS` |
| Shower timer remaining | `set:ste.app.showerTimer:remainingMilliseconds`, displayed as `M:SS` |

Consumption sensors expose the raw chart values as attributes and the EUR total reported by the DHE as `cost_eur`.

### Controls

| Entity | Type | Source / behavior |
|---|---|---|
| Eco mode | Switch | ODB ID `6` |
| Wannenfüllung / Bath fill | Switch | ODB ID `1`; on starts, off stops |
| Eco flow limit | Number | ODB ID `7`, values `6`, `7` or `8 L/min` |
| Maximum temperature | Number | ODB ID `5`, range `30` to `50 °C` |
| Bath fill target volume | Number | ODB ID `3`, unit `L` |
| Brush timer | Switch | `assign:ste.app.brushTimer:activation`; on starts, off stops |
| Shower timer | Switch | `assign:ste.app.showerTimer:activation`; on starts, off stops |
| Brush timer duration | Number | `assign:ste.app.brushTimer:durationMilliseconds`, max. `20 min` |
| Shower timer duration | Number | `assign:ste.app.showerTimer:durationMilliseconds`, max. `20 min` |
| Reset brush timer | Button | `assign:ste.app.brushTimer:reset` |
| Reset shower timer | Button | `assign:ste.app.showerTimer:reset` |
| Wellness cold prevention | Switch | ODB ID `2`; on sets value `1`, off sends stop trigger |
| Wellness shower program winter refresh | Button | ODB ID `2` value `2` + ODB ID `10` trigger |
| Wellness shower program summer fitness | Button | ODB ID `2` value `3` + ODB ID `10` trigger |
| Wellness shower program circulation support | Button | ODB ID `2` value `4` + ODB ID `10` trigger |

## DHE protocol notes

The integration keeps one long-polling session open, answers Engine.IO pings and processes incoming DHE messages from that session. At startup it requests the known ODB IDs and the DHE app timer and consumption values once to seed Home Assistant state.

Writable ODB settings are sent through `assign:ste.common.odb:value`. App timer commands are sent through `assign:ste.app.brushTimer:*` and `assign:ste.app.showerTimer:*` with Socket.IO message IDs matching the DHE web UI format.

More timer protocol details are documented in [`APP_TIMER_PROTOCOL.md`](APP_TIMER_PROTOCOL.md).

## Installation via HACS custom repository

1. Open HACS.
2. Go to `Integrations` -> three-dot menu -> `Custom repositories`.
3. Add repository URL `https://github.com/memphi2/ha-dhe-connect`.
4. Choose category `Integration`.
5. Install the integration.
6. Restart Home Assistant.
7. Add `Stiebel DHE Connect` from `Settings` -> `Devices & services`.

## Manual installation

Copy the integration folder to:

```text
/config/custom_components > stiebel_dhe_connect/
```

Restart Home Assistant and add the integration through the UI.

## Configuration

The config flow asks for:

| Field | Example |
|---|---|
| IP address or hostname | `172.16.2.124` |
| Port | `8443` |
| Device name | `DHE Connect` |

The host field accepts only an IP address or hostname. Paths, usernames, query strings and embedded ports are rejected. The port must be between `1` and `65535`.

## Pairing and token

On first connection the DHE may request pairing. Confirm pairing on the DHE when prompted.

The token is stored locally at:

```text
/config/.storage/stiebel_dhe_connect_token.txt
```

To pair again, delete this file and reload or restart Home Assistant.

## Security notes

- Use this integration only on a trusted local network.
- Do not expose the DHE web interface or port `8443` to the internet.
- The token is stored in the Home Assistant configuration directory.
- The integration tries to set token file permissions to `0600`; actual enforcement depends on the Home Assistant filesystem.
- Tokens are not intentionally written to normal logs.

## Troubleshooting

| Symptom | Check |
|---|---|
| Integration unavailable | Verify IP address, port and browser access to the DHE web UI |
| Pairing repeats | Delete the token file and pair again |
| Writing fails | Verify that the DHE is locally reachable on port `8443` |
| Temperature does not change | Check DHE limits, locks or device mode |
| Switches missing | Update to `0.7.5` or newer, restart Home Assistant and reload the integration |
| Timer reset does not update immediately | Check whether the DHE accepts the matching `brushTimer` or `showerTimer` reset command |
