# Release v0.4.6

## Contents

- HACS-compatible Home Assistant custom integration for Stiebel DHE Connect.
- Persistent Engine.IO v3 / Socket.IO long-polling session.
- Displayed target temperature read through ODB ID `0`.
- Current water consumption sensor from ODB ID `15` with `flow_l_min = ODB_ID_15 / 10`.
- Current power consumption sensor from ODB ID `16` with `power_kw = ODB_ID_16 / 100 * 24`.
- Temperature writes through ODB ID `66` with readback through ODB ID `0`.
- UI configuration through the Home Assistant config flow.
- English and German Home Assistant UI translations.
- Repository metadata for `memphi2/ha-dhe-connect`.

## Installation via HACS Custom Repository

Repository URL: `https://github.com/memphi2/ha-dhe-connect`
Category: `Integration`
