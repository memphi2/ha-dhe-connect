# Changelog

## 0.7.2

- Remove `custom_components/stiebel_dhe_connect/strings.json`; custom integrations should provide translations through `translations/*.json`.
- Keep the existing complete English and German translation files.
- Bump integration version to `0.7.2`.

## 0.7.1

- Fix Home Assistant startup failure for app timer switch entities.
- Make `StiebelDHEAppTimerSwitchDescription` extend `SwitchEntityDescription` so Home Assistant can access the expected switch entity description attributes.

## 0.7.0

- Bump integration version to `0.7.0`.
- Clean up root README, component README, HACS info and app timer protocol notes.
- Remove outdated release-focus text and duplicated documentation blocks.
- Keep documentation focused on the current entity set, local protocol behavior and HACS installation.
- Keep brand icons documented as part of the repository layout.

## 0.6.8

- Add explicit start and stop button entities for the brush timer.
- Add explicit start and stop button entities for the shower timer.
- Limit brush and shower timer duration numbers to a maximum of 20 minutes.
- Display brush and shower timer remaining time as `M:SS` instead of numeric minutes.
- Keep the existing timer activation switches, duration numbers, remaining sensors and reset buttons.
- Add English and German translations for the new timer start/stop buttons.

## 0.6.7

- Show brush and shower timer activation switches as normal device controls instead of configuration entities.
- Keep the brush and shower timer remaining sensors unchanged.
- Use stable timer icons for brush and shower reset buttons.

## 0.6.6

- Document the observed DHE app timer Socket.IO wire format.
- Keep brush and shower timer remaining sensors in scope.
- Clarify app timer activation start/stop commands and `set:` confirmation messages.
- Use a shower-specific icon for the shower timer activation switch.

## 0.6.5

- Add week, year and multi-year water consumption sensors from DHE app consumption messages.
- Add week, year and multi-year energy consumption sensors from DHE app consumption messages.
- Request the DHE app consumption values once after session startup.
- Store the DHE chart values and EUR sum as sensor attributes for the consumption entities.
- Document the `ste.app.consumption` message commands and their units.
- Request app timer activation, duration and remaining-time values once after session startup.
- Add reset buttons for brush timer and shower timer.
- Send DHE app timer messages with Socket.IO message ids matching the web UI format.
- Keep app timer setting entities on the requested value if the DHE performs the command but does not send a matching app confirmation event.

## 0.6.4

- Support optional DHE `websocketSid` values in polling URLs.
- Add separate brush timer and shower timer activation, duration and remaining-time entities.
- Handle both `ste.app.brushTimer` and `ste.app.showerTimer` app timer message paths.
- Confirm app timer writes from matching timer events instead of synthetic ODB readbacks.
- Refresh README, HACS info text and release notes for `v0.6.4`.

## 0.6.3

- Harden writable configuration entities against temporary readback delays.
- Harden target-temperature writes with repeated readback confirmation.
- Accept both raw and already scaled readbacks for Eco flow limit and maximum temperature.
- Restore last known number and Eco mode states after Home Assistant reloads to avoid unknown states.

## 0.6.2

- Write maximum temperature as raw tenths of a degree, e.g. `45.0 degrees C` as `450`.
- Request ODB readback after writable setting changes so Eco flow limit, maximum temperature and bath-fill settings can confirm reliably.

## 0.6.1

- Add writable Eco mode, Eco flow limit, maximum temperature and bath-fill controls.
- Add bath-fill start and stop buttons.
- Request ODB IDs `1`, `3`, `5`, `6` and `7` at session startup for the new control entities.
- Rename the instantaneous water metric to current water flow while keeping the `volume_flow_rate` device class and `L/min` unit.
- Add base translations for the new button, number and switch entities.
- Add device classes and icons for configuration number entities.

## 0.5.2

- Remove the configurable 600-second value polling interval.
- Request ODB values once after session startup and rely on incoming DHE messages afterward.
- Remove value polling from the config and options flow.
- Mark the integration as `local_push`.

## 0.4.7

- Read configured DHE power from ODB ID `20` once after session startup.
- Add a configured power sensor.
- Calculate current power consumption with configured power instead of the fixed `24 kW` multiplier.

## 0.4.6

- Convert README, component README, release notes and HACS info text to English.
- Add Home Assistant translation files for English and German.
- Move sensor display names into Home Assistant entity translations.
- Move config flow text to English base strings with German translation override.

## 0.4.5

- Add `sensor` platform support for current water flow from ODB ID `15`.
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
