# Stiebel DHE Connect

Local Home Assistant integration for Stiebel Eltron DHE Connect devices.

Repository: `memphi2/ha-dhe-connect`.

## 0.6.8

This version adds explicit start and stop button entities for the brush timer and shower timer. The timer activation switches remain available.

Brush and shower timer duration numbers are limited to a maximum of `20 min`. Brush and shower timer remaining sensors display their value as `M:SS`.

## Functionality

The integration keeps one Socket.IO / Engine.IO v3 long-polling connection open, answers Engine.IO pings, requests ODB IDs `0`, `1`, `3`, `5`, `6`, `7`, `15`, `16` and `20` plus DHE app timer and consumption values once after session startup, and then updates values from incoming DHE messages.

Temperature writes use ODB ID `66` with readback through ODB ID `0`. Eco mode, Eco flow limit, maximum temperature and bath-fill controls use the corresponding writable ODB IDs, request readback after assignment and wait for DHE confirmation.

The integration handles both DHE app timer paths, `ste.app.brushTimer` and `ste.app.showerTimer`, as separate Home Assistant entities for activation, duration, reset and remaining time.

Water and energy consumption messages from `ste.app.consumption` are requested after startup and exposed as week, year and multi-year sensors. The DHE chart values are summed as the sensor state, while the EUR total sent as `sum` is exposed as the `cost_eur` attribute.
