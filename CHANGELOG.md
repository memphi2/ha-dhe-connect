# Changelog

## v0.4.1

- Repository metadata set to `memphi2/ha-dhe-connect`.
- Manifest documentation and issue tracker URLs updated.
- Code owner set to `@memphi2`.
- README extended with upload and release steps.

## v0.4.0

- Persistent open Socket.IO/Engine.IO-v3 long-polling connection.
- Replaced HTTP availability ping with periodic setpoint polling of ODB ID `0`, default `600 s`.
- Engine.IO ping/pong handling added to keep the session alive.
- Temperature writes now use the open session and wait for matching ODB ID `0` readback.
- `poll_interval` replaces `ping_interval`; existing config entries keep working through compatibility fallback.

## v0.3.0

- Hardened host, port and ping interval validation.
- Added atomic token writes and best-effort `0600` token file permissions.
- Reduced startup read to one Socket.IO session.
- Reduced write retries to two attempts.
- Added Home Assistant device info.
- Added security documentation.

## v0.2.1

- HACS-compatible repository layout.
- Added README, `hacs.json` and license.

## v0.2.0

- Added UI config flow.
- Added short-lived Socket.IO sessions only.
- Added lightweight availability ping.
