# Stiebel DHE Connect for Home Assistant

Custom Home Assistant integration for Stiebel Eltron DHE Connect instantaneous water heaters through the local Socket.IO / Engine.IO v3 long-polling interface.

The integration is intended for use on a trusted local network. It exposes a `climate` entity for reading and setting the displayed target temperature, sensors for current water consumption and current power consumption, plus controls for Eco mode, maximum temperature and bath-fill settings.

## Status

Experimental custom integration. Tested against a locally reachable DHE Connect on port `8443`.

## Features

- UI-based Home Assistant config flow, no YAML required.
- Configurable IP address or hostname, port and device name.
- Local operation without cloud access.
- Token is stored locally in Home Assistant.
- Keeps one Socket.IO / Engine.IO long-polling session open after Home Assistant starts.
- Responds to Engine.IO pings and reconnects automatically if the DHE closes the session.
- Requests ODB IDs `0`, `1`, `3`, `5`, `6`, `7`, `15`, `16` and `20` after session startup and then updates from incoming DHE events.
- Writes temperature changes through ODB ID `66` and reads back ODB ID `0` on the existing session.
- Writes Eco mode, Eco flow limit, maximum temperature and bath-fill settings through `assign:ste.common.odb:value` and waits for the DHE to confirm the written id/value pair.
- Sensor `Current water consumption`: ODB ID `15` / `10` in `L/min`.
- Sensor `Configured power`: ODB ID `20` in `kW`.
- Sensor `Current power consumption`: ODB ID `16` / `100` * configured power in `kW`.
- Switch `Eco mode`: ODB ID `6`.
- Number `Eco flow limit`: ODB ID `7` in `L/min`.
- Number `Maximum temperature`: ODB ID `5` in `degrees C`.
- Number `Bath fill target volume`: ODB ID `3` in `L`.
- Buttons `Start bath fill` and `Stop bath fill`: ODB ID `1` with `true` / `false`.
- Home Assistant UI strings are available in English and German.

## ODB IDs

| Purpose | Command | ODB ID | Scaling / value |
|---|---|---:|---|
| Read displayed target temperature | `get:ste.common.odb:value` | `0` | raw tenths of `degrees C` |
| Start / stop bath fill | `assign:ste.common.odb:value` | `1` | `true` / `false` |
| Set bath fill target volume | `assign:ste.common.odb:value` | `3` | `L` |
| Set maximum temperature | `assign:ste.common.odb:value` | `5` | `degrees C` |
| Enable / disable Eco mode | `assign:ste.common.odb:value` | `6` | `true` / `false` |
| Set Eco flow limit | `assign:ste.common.odb:value` | `7` | `L/min` |
| Read current water consumption | `get:ste.common.odb:value` | `15` | raw `/ 10` in `L/min` |
| Read current power consumption | `get:ste.common.odb:value` | `16` | raw `/ 100 * configured power` in `kW` |
| Read configured power | `get:ste.common.odb:value` | `20` | `kW` |
| Set displayed target temperature | `assign:ste.common.odb:value` | `66` | raw request value with UI addressing bits |

Temperature values for ODB ID `0` are transferred in tenths of a degree, for example `345` for `34.5 degrees C`. Current water consumption is calculated as `ODB ID 15 / 10` in `L/min`. Configured power is read from ODB ID `20` once after startup and is expected to be `18` through `24 kW`. Current power consumption is calculated as `ODB ID 16 / 100 * configured power` in `kW`. Writes through ID `66` also use the request addressing known from the DHE web UI in the upper bits.

The writable setting IDs use the generic Socket.IO message command `assign:ste.common.odb:value`. The integration waits until the DHE sends back the same ODB id and confirmed value before updating the Home Assistant entity state.

## HACS Installation

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

## Manual Installation

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

## Pairing and Token

On first connection the DHE may request pairing. Confirm pairing on the DHE when prompted.

The token is stored locally at:

```text
/config/.storage/stiebel_dhe_connect_token.txt
```

To pair again, delete this file and restart Home Assistant or reload the integration.

## Connection Behavior

- Startup: open session, check or refresh token, authenticate.
- Runtime: keep long-polling GETs open and answer Engine.IO pings.
- After startup: request ODB IDs `0`, `1`, `3`, `5`, `6`, `7`, `15`, `16` and `20` once to seed entity state.
- Runtime updates: process incoming DHE ODB messages from the open session.
- Temperature change: write ODB ID `66` through the same session and read back ODB ID `0`.
- Setting changes: write the respective ODB id through `assign:ste.common.odb:value` and wait for the id/value confirmation from the DHE.
- Session close: entity becomes temporarily unavailable or reconnecting, then reconnects automatically.

## Security Notes

- Use this integration only on a trusted local network.
- Do not expose DHE port `8443` to the internet.
- The token is stored in the Home Assistant configuration directory. The integration tries to set file permissions to `0600`; actual enforcement depends on the Home Assistant filesystem.
- Tokens are not intentionally written to normal logs. Still avoid sharing debug raw data publicly.
- The integration uses HTTP to the local DHE web interface because the device exposes the local interface this way.
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
| Setting change times out | Check whether the DHE sends back the expected id/value confirmation |

## Startup Behavior

The persistent DHE session runs as a Home Assistant background task and should not block Home Assistant startup.
