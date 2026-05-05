# Stiebel DHE Connect for Home Assistant

Custom Home Assistant integration for Stiebel Eltron DHE Connect instantaneous water heaters through the local Socket.IO / Engine.IO v3 long-polling interface.

The integration is intended for use on a trusted local network. It exposes a `climate` entity for reading and setting the displayed target temperature, plus sensors for current water consumption and current power consumption.

## Status

Experimental custom integration. Tested against a locally reachable DHE Connect on port `8443`.

## Features

- UI-based Home Assistant config flow, no YAML required.
- Configurable IP address or hostname, port, device name and value polling interval.
- Local operation without cloud access.
- Token is stored locally in Home Assistant.
- Keeps one Socket.IO / Engine.IO long-polling session open after Home Assistant starts.
- Responds to Engine.IO pings and reconnects automatically if the DHE closes the session.
- Polls ODB IDs `0`, `15` and `16` at the configured interval, default `600` seconds.
- Writes temperature changes through ODB ID `66` and reads back ODB ID `0` on the existing session.
- Sensor `Current water consumption`: ODB ID `15` / `10` in `L/min`.
- Sensor `Current power consumption`: ODB ID `16` / `100` * `24` in `kW`.
- Keeps entities visible; availability is based on the persistent DHE session instead of a separate HTTP ping.
- Home Assistant UI strings are available in English and German.

## ODB IDs

| Purpose | Command | ODB ID |
|---|---|---:|
| Read displayed target temperature | `get:ste.common.odb:value` | `0` |
| Read current water consumption | `get:ste.common.odb:value` | `15` |
| Read current power consumption | `get:ste.common.odb:value` | `16` |
| Set displayed target temperature | `assign:ste.common.odb:value` | `66` |

Temperature values are transferred in tenths of a degree, for example `345` for `34.5 degrees C`. Current water consumption is calculated as `ODB ID 15 / 10` in `L/min`. Current power consumption is calculated as `ODB ID 16 / 100 * 24` in `kW`. Writes through ID `66` also use the request addressing known from the DHE web UI in the upper bits.

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
| Value polling | Read interval for ODB IDs `0`, `15` and `16` in seconds | `600` |

Input is validated: host must be an IP address or hostname only; paths, usernames, query strings and embedded ports are rejected. The port must be between `1` and `65535`. Value polling must be between `60` and `86400` seconds.

## Pairing and Token

On first connection the DHE may request pairing. Confirm pairing on the DHE when prompted.

The token is stored locally at:

```text
/config/.storage/stiebel_dhe_connect_token.txt
```

To pair again, delete this file and restart Home Assistant or reload the integration.

## Connection Behavior

Since v0.4.0 the integration keeps one Socket.IO / Engine.IO v3 long-polling session open. This matters for this device because Engine.IO expects ping / pong frames during longer idle periods.

- Startup: open session, check or refresh token, authenticate.
- Runtime: keep long-polling GETs open and answer Engine.IO pings.
- Every configured `poll_interval` seconds: read ODB IDs `0`, `15` and `16`.
- Temperature change: write ODB ID `66` through the same session and read back ODB ID `0`.
- Session close: entity becomes temporarily unavailable or reconnecting, then reconnects automatically.

## Security Notes

- Use this integration only on a trusted local network.
- Do not expose DHE port `8443` to the internet.
- The token is stored in the Home Assistant configuration directory. The integration tries to set file permissions to `0600`; actual enforcement depends on the Home Assistant filesystem.
- Tokens are not intentionally written to normal logs. Still avoid sharing debug raw data publicly.
- The integration uses HTTP to the local DHE web interface because the device exposes the local interface this way.
- The integration limits the settable temperature to `20.0 degrees C` through `60.0 degrees C` and rounds to `0.5 degrees C`.

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

## Startup Behavior

Since v0.4.2 the persistent DHE polling loop is scheduled as a Home Assistant background task. This avoids keeping Home Assistant in the startup phase while the long-polling connection is active.
