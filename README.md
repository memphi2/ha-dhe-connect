# Stiebel DHE Connect for Home Assistant

Custom Home Assistant integration for Stiebel Eltron DHE Connect instantaneous water heaters.

The integration talks to the local DHE web interface through the device's Socket.IO / Engine.IO v3 long-polling endpoint. It is intended for trusted local networks and does not use a cloud service.

## Status

Experimental custom integration. Tested with a locally reachable DHE Connect on port `8443`.

Current version: `0.7.10` (optimized startup value reads).

## Features

- UI-based Home Assistant config flow.
- Local connection by IP address or hostname.
- Persistent Socket.IO / Engine.IO v3 long-polling session with lightweight callback dispatching.
- Automatic reconnect if the DHE closes the session.
- Best-effort startup reads for all currently known DHE web UI values.
- Target-temperature control through the existing DHE ODB interface.
- Current water flow, current power, configured power, app consumption, last usage and saving monitor sensors.
- Diagnostic online status and reconnect count entities.
- Eco mode, Eco flow limit, maximum temperature and bath-fill controls.
- Separate brush timer and shower timer controls.
- Timer reset buttons.
- Temperature memory preset buttons for DHE memory slots 1 and 2.
- Box-style number inputs for temperature memory values and timer durations.
- Wellness program switches (winter refresh, summer fitness, circulation support,cold prevention).
- Bath fill and timer start/stop via switches.


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
| Last usage water | `set:ste.app.consumption:lastUsage`, unit `L` |
| Last usage energy | `set:ste.app.consumption:lastUsage`, unit `kWh` |
| Last usage duration | `set:ste.app.consumption:lastUsage`, unit `min` |
| Last usage cost | `set:ste.app.consumption:lastUsage`, unit `EUR` |
| Saving monitor water | `set:ste.app.savingMonitor:consumption`, unit `L` |
| Saving monitor energy | `set:ste.app.savingMonitor:consumption`, unit `kWh` |
| Saving monitor CO2 | `set:ste.app.savingMonitor:consumption`, unit `kg` |
| Saving monitor activation rate | `set:ste.app.savingMonitor:ActivationRate` |
| Brush timer remaining | `set:ste.app.brushTimer:remainingMilliseconds`, displayed as `M:SS` |
| Shower timer remaining | `set:ste.app.showerTimer:remainingMilliseconds`, displayed as `M:SS` |

Consumption sensors expose the raw chart values as attributes and the EUR total reported by the DHE as `cost_eur`. Saving monitor sensors expose the latest possible, real and consumption payloads as attributes.

### Diagnostics

| Entity | Type | Source / behavior |
|---|---|---|
| Online | Binary sensor | Current authenticated persistent session status |
| Reconnects | Sensor | Number of successful reconnects after the initial connection |
| Device info | Sensor | Device type plus version, WLAN/Bluetooth and service attributes |
| Unhandled ODB values | Sensor | Count and attributes for valid unknown or invalid ODB readbacks |

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
| Brush timer duration | Number box | `assign:ste.app.brushTimer:durationMilliseconds`, max. `20 min` |
| Shower timer duration | Number box | `assign:ste.app.showerTimer:durationMilliseconds`, max. `20 min` |
| Reset brush timer | Button | `assign:ste.app.brushTimer:reset` |
| Reset shower timer | Button | `assign:ste.app.showerTimer:reset` |
| Temperature memory 1 | Button | ODB ID `66` command built from stored memory 1 temperature |
| Temperature memory 2 | Button | ODB ID `66` command built from stored memory 2 temperature |
| Temperature memory 1 temperature | Number box | `assign:ste.common.temperature:memory`, memory ID `0` |
| Temperature memory 2 temperature | Number box | `assign:ste.common.temperature:memory`, memory ID `1` |
| Cold prevention | Switch | ODB ID `2`; on sets value `1` + ODB ID `10` trigger; off sends stop |
| Winter refresh | Switch | ODB ID `2` value `2` + ODB ID `10` trigger; off sends stop |
| Summer fitness | Switch | ODB ID `2` value `3` + ODB ID `10` trigger; off sends stop |
| Circulation support | Switch | ODB ID `2` value `4` + ODB ID `10` trigger; off sends stop |

## DHE protocol notes

The integration keeps one long-polling session open, answers Engine.IO pings and processes incoming DHE messages from that session. At startup it first requests the required entity seed values, then requests all currently known additional DHE web UI values best-effort. Optional reads cover remaining readable ODB ID `4`, temperature memory values, consumption volume format and last usage, saving monitor values, version/device information, wellness programs and maximum override. ODB ID `66` is command-only and is not read at startup. Optional responses are cached internally and only selected diagnostics create Home Assistant entities.

Writable ODB settings are sent through `assign:ste.common.odb:value`. Temperature memory preset buttons send ODB ID `66` commands built from the currently stored temperature memory values. Temperature memory number boxes use `assign:ste.common.temperature:memory` with `operation: add_change` and accept both list and single-object memory responses. App timer commands are sent through `assign:ste.app.brushTimer:*` and `assign:ste.app.showerTimer:*` with Socket.IO message IDs matching the DHE web UI format.

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
| Timer reset does not update immediately | Check whether the DHE accepts the matching `brushTimer` or `showerTimer` reset command |
