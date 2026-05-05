# Changelog

## 0.4.5

- Add `sensor` platform support for current water consumption from ODB ID `15`.
- Add current power consumption sensor from ODB ID `16`.
- Poll ODB IDs `0`, `15` and `16` over the existing persistent DHE session.
- Document conversion formulas: `flow_l_min = ODB_ID_15 / 10` and `power_kw = ODB_ID_16 / 100 * 24`.

## 0.4.4

- Keep the climate entity available during short DHE long-polling reconnect phases after a valid setpoint has been read.
- Add a `connection_state` diagnostic attribute with `starting`, `connected`, `reconnecting` or `unavailable`.
- Clarify that pairing must be confirmed on the DHE when no valid token is present.
- Clean up README wording and reduce obsolete release/upload notes.

## 0.4.3

- Keep the Socket.IO/Engine.IO long-polling session open after startup.
- Replace separate HTTP ping with periodic setpoint polling.
- Poll ODB ID 0 every 600 seconds by default.
- Use the existing session for setpoint writes via ODB ID 66.
- Improve reconnect handling when the DHE closes the session.

## 0.4.2

- Schedule the persistent Engine.IO/Socket.IO polling loop as a Home Assistant background task.
- Prevent the long-running DHE connection task from holding Home Assistant in the startup phase.
- No protocol change: the connection is still kept open and ODB ID 0 is polled every configured interval.

## 0.4.1

- Repository metadata set to `memphi2/ha-dhe-connect`.
- Manifest documentation and issue tracker URLs updated.
- Code owner set to `@memphi2`.
- README extended with upload and release steps.

## 0.4.0

- Persistent open Socket.IO/Engine.IO-v3 long-polling connection.
- Replaced HTTP availability ping with periodic setpoint polling of ODB ID `0`, default `600 s`.
- Engine.IO ping/pong handling added to keep the session alive.
- Temperature writes now use the open session and wait for matching ODB ID `0` readback.
- `poll_interval` replaces `ping_interval`; existing config entries keep working through compatibility fallback.

## 0.3.0

- Hardened host, port and ping interval validation.
- Added atomic token writes and best-effort `0600` token file permissions.
- Reduced startup read to one Socket.IO session.
- Reduced write retries to two attempts.
- Added Home Assistant device info.
- Added security documentation.

## 0.2.1

- HACS-compatible repository layout.
- Added README, `hacs.json` and license.

## 0.2.0

- Added UI config flow.
- Added short-lived Socket.IO sessions only.
- Added lightweight availability ping.
