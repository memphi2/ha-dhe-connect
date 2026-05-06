# Stiebel DHE Connect for Home Assistant

Custom Home Assistant integration for Stiebel Eltron DHE Connect instantaneous water heaters through the local Socket.IO / Engine.IO v3 long-polling interface.

The integration is intended for use on a trusted local network. It exposes a `climate` entity for the displayed target temperature, sensors for current values and DHE app consumption charts, and controls for Eco mode, maximum temperature, bath filling and the DHE app timers.

## Status

Experimental custom integration. Tested against a locally reachable DHE Connect on port `8443`.

## Version 0.6.8 focus

- Adds explicit start and stop button entities for the brush timer.
- Adds explicit start and stop button entities for the shower timer.
- Limits brush and shower timer duration numbers to a maximum of 20 minutes.
- Displays brush and shower timer remaining time as `M:SS`.
- Keeps the existing timer activation switches, duration numbers, remaining sensors and reset buttons.
- Adds English and German translations for the new timer start/stop buttons.

## Features

- UI-based Home Assistant config flow, no YAML required.
- Configurable IP address or hostname, port and device name.
- Local operation without cloud access.
- Token is stored locally in Home Assistant.
- Keeps one Socket.IO / Engine.IO long-polling session open after Home Assistant starts.
- Responds to Engine.IO pings and reconnects automatically if the DHE closes the session.
- Requests ODB IDs `0`, `1`, `3`, `5`, `6`, `7`, `15`, `16` and `20` after session startup and then updates from incoming DHE events.
- Requests DHE app timer activation, duration and remaining-time values after session startup.
- Requests DHE app consumption week/year/year-series values after session startup.
- Processes app timer messages from both `ste.app.brushTimer` and `ste.app.showerTimer`.
- Writes app timer activation and duration commands with Socket.IO message IDs matching the DHE web UI format.
- Processes consumption messages from `ste.app.consumption` for water and energy week/year/year-series charts.
- Keeps entities visible; availability is based on the persistent DHE session instead of a separate HTTP ping.
- Home Assistant UI strings are available in English and German.

## Home Assistant entities

### Climate

| Entity | Source / behavior |
|---|---|
| Displayed target temperature | ODB ID `0`, written through ODB ID `66` with readback confirmation |

### Sensors

| Entity | Source / scaling |
|---|---|
| Current water flow | ODB ID `15` / `10` in `L/min` |
| Current power consumption | ODB ID `16` / `100 * configured_power_kw` in `kW` |
| Configured power | ODB ID `20` in `kW` |
| Water consumption week | `set:ste.app.consumption:waterWeek`, chart sum in `L`, EUR sum as `cost_eur` |
| Water consumption year | `set:ste.app.consumption:waterYear`, chart sum in `m3`, EUR sum as `cost_eur` |
| Water consumption years | `set:ste.app.consumption:waterYears`, chart sum in `m3`, EUR sum as `cost_eur` |
| Energy consumption week | `set:ste.app.consumption:energyWeek`, chart sum in `kWh`, EUR sum as `cost_eur` |
| Energy consumption year | `set:ste.app.consumption:energyYear`, chart sum in `kWh`, EUR sum as `cost_eur` |
| Energy consumption years | `set:ste.app.consumption:energyYears`, chart sum in `kWh`, EUR sum as `cost_eur` |
| Brush timer remaining | `set:ste.app.brushTimer:remainingMilliseconds`, displayed as `M:SS` |
| Shower timer remaining | `set:ste.app.showerTimer:remainingMilliseconds`, displayed as `M:SS` |

### Controls

| Entity | Type | Source / behavior |
|---|---|---|
| Eco mode | Switch | ODB ID `6` |
| Brush timer | Switch | `assign:ste.app.brushTimer:activation`, `true` starts and `false` stops |
| Shower timer | Switch | `assign:ste.app.showerTimer:activation`, `true` starts and `false` stops |
| Eco flow limit | Number | ODB ID `7`, raw `/ 10`, selectable as `6`, `7` or `8 L/min` |
| Maximum temperature | Number | ODB ID `5`, selectable from `30` to `50 degrees C` |
| Bath fill target volume | Number | ODB ID `3` in `L` |
| Brush timer duration | Number | `assign:ste.app.brushTimer:durationMilliseconds`, displayed in minutes, maximum `20 min` |
| Shower timer duration | Number | `assign:ste.app.showerTimer:durationMilliseconds`, displayed in minutes, maximum `20 min` |
| Start bath fill | Button | ODB ID `1` with `true` |
| Stop bath fill | Button | ODB ID `1` with `false` |
| Start brush timer | Button | `assign:ste.app.brushTimer:activation` with `true` |
| Stop brush timer | Button | `assign:ste.app.brushTimer:activation` with `false` |
| Start shower timer | Button | `assign:ste.app.showerTimer:activation` with `true` |
| Stop shower timer | Button | `assign:ste.app.showerTimer:activation` with `false` |
| Reset brush timer | Button | `assign:ste.app.brushTimer:reset` |
| Reset shower timer | Button | `assign:ste.app.showerTimer:reset` |

## ODB IDs

| Purpose | Command | ODB ID | Scaling / value |
|---|---|---:|---|
| Read displayed target temperature | `get:ste.common.odb:value` | `0` | raw tenths of `degrees C` |
| Start / stop bath fill | `assign:ste.common.odb:value` | `1` | `true` / `false` |
| Set bath fill target volume | `assign:ste.common.odb:value` | `3` | `L` |
| Set maximum temperature | `assign:ste.common.odb:value` | `5` | raw tenths of `degrees C`, selectable as `30` to `50 degrees C` |
| Enable / disable Eco mode | `assign:ste.common.odb:value` | `6` | `true` / `false` |
| Set Eco flow limit | `assign:ste.common.odb:value` | `7` | raw `/ 10`, values `60`, `70`, `80` => `6`, `7`, `8 L/min` |
| Read current water flow | `get:ste.common.odb:value` | `15` | raw `/ 10` in `L/min` |
| Read current power consumption | `get:ste.common.odb:value` | `16` | raw `/ 100 * configured power` in `kW` |
| Read configured power | `get:ste.common.odb:value` | `20` | `kW` |
| Set displayed target temperature | `assign:ste.common.odb:value` | `66` | raw request value with UI addressing bits |

Temperature values for ODB IDs `0` and `5` are transferred in tenths of a degree, for example `345` for `34.5 degrees C`. Current water flow is calculated as `ODB ID 15 / 10` in `L/min`. Eco flow limit values on ODB ID `7` are also transferred as tenths, for example `60` for `6 L/min`. Configured power is read from ODB ID `20` once after startup and is expected to be `18` through `24 kW`. Current power consumption is calculated as `ODB ID 16 / 100 * configured power` in `kW`.

The writable setting IDs use the generic Socket.IO message command `assign:ste.common.odb:value`. The integration waits until the DHE sends back the same ODB id and confirmed value before updating the Home Assistant entity state.

## App timer commands

The DHE exposes both app timer paths below. The integration keeps them as separate Home Assistant entities and updates them from both `set:` and `assign:` messages.

| Purpose | Command | Scaling / value |
|---|---|---|
| Enable / disable brush timer | `assign:ste.app.brushTimer:activation` | `true` / `false` |
| Set brush timer duration | `assign:ste.app.brushTimer:durationMilliseconds` | milliseconds, displayed as minutes, maximum `20 min` |
| Read brush timer remaining time | `set:ste.app.brushTimer:remainingMilliseconds` | milliseconds, displayed as `M:SS` |
| Reset brush timer | `assign:ste.app.brushTimer:reset` | `true`, clears remaining time locally |
| Enable / disable shower timer | `assign:ste.app.showerTimer:activation` | `true` / `false` |
| Set shower timer duration | `assign:ste.app.showerTimer:durationMilliseconds` | milliseconds, displayed as minutes, maximum `20 min` |
| Read shower timer remaining time | `set:ste.app.showerTimer:remainingMilliseconds` | milliseconds, displayed as `M:SS` |
| Reset shower timer | `assign:ste.app.showerTimer:reset` | `true`, clears remaining time locally |

The observed Socket.IO wire format for the app timers is documented in [`APP_TIMER_PROTOCOL.md`](../../APP_TIMER_PROTOCOL.md).

## Consumption commands

The DHE sends consumption data as app messages. The `chart` array contains the consumption values shown in the DHE UI. The `sum` value matches the EUR total shown by the DHE and is exposed as the `cost_eur` attribute.

| Purpose | Command | Sensor unit |
|---|---|---|
| Water consumption week | `set:ste.app.consumption:waterWeek` | `L` |
| Water consumption year | `set:ste.app.consumption:waterYear` | `m3` |
| Water consumption years | `set:ste.app.consumption:waterYears` | `m3` |
| Energy consumption week | `set:ste.app.consumption:energyWeek` | `kWh` |
| Energy consumption year | `set:ste.app.consumption:energyYear` | `kWh` |
| Energy consumption years | `set:ste.app.consumption:energyYears` | `kWh` |

## Installation via HACS custom repository

1. Open HACS:

```text
HACS -> Integrations -> Three dots -> Custom repositories
```

2. Add repository URL `https://github.com/memphi2/ha-dhe-connect` and choose category `Integration`.
3. Install the integration.
4. Restart Home Assistant.
5. Add the integration:

```text
Settings -> Devices & services -> Add integration -> Stiebel DHE Connect
```

## Manual installation

Copy the integration folder to:

```text
/config/custom_components/stiebel_dhe_connect/
```

Then restart Home Assistant and add the integration through the UI.

## Configuration

The Home Assistant UI asks for:

| Field | Meaning | Example |
|---|---|---|
| IP address or hostname | DHE address on the local network | `172.16.2.124` |
| Port | HTTP / Socket.IO port | `8443` |
| Device name | Name shown in Home Assistant | `DHE Connect` |

Input is validated: host must be an IP address or hostname only; paths, usernames, query strings and embedded ports are rejected. The port must be between `1` and `65535`.

## Pairing and token

On first connection the DHE may request pairing. Confirm pairing on the DHE when prompted.

The token is stored locally at:

```text
/config/.storage/stiebel_dhe_connect_token.txt
```

To pair again, delete this file and restart Home Assistant or reload the integration.

## Connection behavior

- Startup: open session, check or refresh token, authenticate.
- Runtime: keep long-polling GETs open and answer Engine.IO pings.
- After startup: request ODB IDs `0`, `1`, `3`, `5`, `6`, `7`, `15`, `16` and `20` once to seed entity state.
- After startup: request app timer activation, duration and remaining-time values for brush and shower timers once.
- After startup: request app consumption values for water and energy week/year/year-series sensors once.
- Runtime updates: process incoming DHE ODB messages from the open session.
- Temperature change: write ODB ID `66` through the same session and read back ODB ID `0`.
- Setting changes: write the respective ODB id through `assign:ste.common.odb:value` and wait for the id/value confirmation from the DHE.
- App timer changes: write the respective app timer command with a Socket.IO message id, use matching timer confirmation events when the DHE sends them, and otherwise keep Home Assistant on the requested value while later push events can still correct the state.
- Consumption updates: process `ste.app.consumption` chart messages from the open session and publish chart totals plus `cost_eur` attributes.
- Session close: entity becomes temporarily unavailable or reconnecting, then reconnects automatically.

## Security notes

- Use this integration only on a trusted local network.
- Do not expose DHE port `8443` to the internet.
- The token is stored in the Home Assistant configuration directory. The integration tries to set file permissions to `0600`; actual enforcement depends on the Home Assistant filesystem.
- Tokens are not intentionally written to normal logs. Still avoid sharing debug raw data publicly.
- The integration uses HTTP to the local DHE web interface because the device exposes the local interface this way.
- The integration limits the settable temperature to `20.0 degrees C` through `60.0 degrees C` and rounds to `0.5 degrees C`.
- Bath fill start/stop is exposed as buttons rather than a switch to avoid accidental persistent switch-state semantics.

## Debugging

Check the Home Assistant log:

```text
Settings -> System -> Logs
```

Common issues:

| Symptom | Cause / solution |
|---|---|
| Integration unavailable | Check IP address and port, test the DHE web UI in a browser |
| Pairing keeps repeating | Delete the token file and pair once again |
| Writing fails | Check whether the DHE is locally reachable on port `8443` |
| Temperature does not change | Check DHE limits, locks or device mode |
| Timer start/stop buttons missing in device controls | Update to `0.6.8` or newer and reload the integration |
| Timer reset does not change immediately | Check whether the DHE accepts the matching `brushTimer` or `showerTimer` reset command |

## Startup behavior

The persistent DHE session runs as a Home Assistant background task and should not block Home Assistant startup.
