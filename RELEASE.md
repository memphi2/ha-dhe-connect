# Release v0.6.7

## Summary

This release fixes the Home Assistant device UI placement for the DHE app timer activation switches and cleans up the release documentation.

## Changes

- Brush timer and shower timer activation switches are now normal device controls instead of configuration entities.
- Brush timer and shower timer remaining sensors remain available.
- Timer reset buttons use stable timer-specific icons:
  - Brush timer reset: `mdi:toothbrush`
  - Shower timer reset: `mdi:shower-head`
- Shower timer activation keeps the `mdi:shower-head` icon.
- Documentation is refreshed and consolidated for the timer controls.

## Existing capabilities retained

- HACS-compatible Home Assistant custom integration for Stiebel DHE Connect.
- Persistent Engine.IO v3 / Socket.IO long-polling session.
- UI configuration through the Home Assistant config flow.
- Displayed target temperature read through ODB ID `0` and written through ODB ID `66`.
- Current water flow sensor from ODB ID `15` with `flow_l_min = ODB_ID_15 / 10`.
- Configured power sensor from ODB ID `20`.
- Current power consumption sensor from ODB ID `16` with `power_kw = ODB_ID_16 / 100 * configured_power_kw`.
- Water and energy consumption sensors from `ste.app.consumption` week/year/year-series chart messages.
- Eco mode, Eco flow limit, maximum temperature and bath-fill controls.
- Brush and shower timer activation switches, duration numbers, remaining sensors and reset buttons.
- App timer writes use Socket.IO message IDs matching the DHE web UI format.
- App timer writes use matching `ste.app.brushTimer` / `ste.app.showerTimer` confirmation events when available and keep the requested value if the DHE does not echo a matching app event.
- German and English Home Assistant UI translations.

## Installation via HACS custom repository

Repository URL: `https://github.com/memphi2/ha-dhe-connect`
Category: `Integration`
