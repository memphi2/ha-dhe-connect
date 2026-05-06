# Release v0.6.6

## Contents

- HACS-compatible Home Assistant custom integration for Stiebel DHE Connect.
- Persistent Engine.IO v3 / Socket.IO long-polling session.
- No periodic 600-second value polling.
- Displayed target temperature read through ODB ID `0`.
- Current water flow sensor from ODB ID `15` with `flow_l_min = ODB_ID_15 / 10`.
- Configured power sensor from ODB ID `20`.
- Current power consumption sensor from ODB ID `16` with `power_kw = ODB_ID_16 / 100 * configured_power_kw`.
- Water consumption sensors for week, year and multi-year DHE app consumption charts.
- Energy consumption sensors for week, year and multi-year DHE app consumption charts.
- Consumption values are requested once after session startup through `get:ste.app.consumption:*`.
- Consumption sensor attributes include the raw chart values, the DHE EUR sum as `cost_eur`, and the source command.
- Eco mode switch from ODB ID `6`.
- Eco flow limit number from ODB ID `7`.
- Maximum temperature number from ODB ID `5`, written as raw tenths of a degree.
- Bath fill target volume number from ODB ID `3`.
- Bath fill start and stop buttons through ODB ID `1`.
- Temperature writes through ODB ID `66` with readback through ODB ID `0`.
- Writable setting changes request ODB readback after assignment and wait for DHE confirmation.
- Optional DHE `websocketSid` values are included in polling URLs when the device provides them.
- Target-temperature and writable-setting confirmations repeat readback without cancelling pending confirmations too early.
- Writable configuration entities restore their last known state after reloads and tolerate raw or scaled readback values.
- Separate brush timer and shower timer activation switches.
- Separate brush timer and shower timer duration numbers, displayed in minutes and written as app timer milliseconds.
- Separate brush timer and shower timer remaining-time sensors, displayed in minutes.
- Brush timer and shower timer reset buttons through the app timer `reset` command.
- App timer values are requested once after startup.
- App timer writes use Socket.IO message ids matching the DHE web UI format.
- App timer writes use matching `ste.app.brushTimer` / `ste.app.showerTimer` confirmation events when available and keep the requested value if the DHE does not echo a matching app event.
- DHE app timer Socket.IO wire format is documented in `APP_TIMER_PROTOCOL.md`.
- Brush and shower timer remaining sensors are explicitly kept in scope.
- Shower timer activation uses the Home Assistant icon `mdi:shower-head`.
- UI configuration through the Home Assistant config flow.
- English and German Home Assistant UI translations.
- Repository metadata for `memphi2/ha-dhe-connect`.

## Installation via HACS Custom Repository

Repository URL: `https://github.com/memphi2/ha-dhe-connect`
Category: `Integration`
