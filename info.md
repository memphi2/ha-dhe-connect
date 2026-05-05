# Stiebel DHE Connect

Local Home Assistant integration for Stiebel Eltron DHE Connect devices.

Repository: `memphi2/ha-dhe-connect`.

This version keeps one Socket.IO / Engine.IO v3 long-polling connection open, answers Engine.IO pings, requests ODB IDs `0`, `1`, `3`, `5`, `6`, `7`, `15`, `16` and `20` once after session startup, and then updates values from incoming DHE messages.

Temperature writes use ODB ID `66` with readback through ODB ID `0`. Eco mode, Eco flow limit, maximum temperature and bath-fill controls use the corresponding writable ODB IDs and wait for DHE writeback confirmation.
