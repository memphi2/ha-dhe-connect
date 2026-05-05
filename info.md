# Stiebel DHE Connect

Local Home Assistant integration for Stiebel Eltron DHE Connect devices.

Repository: `memphi2/ha-dhe-connect`.

This version keeps one Socket.IO / Engine.IO v3 long-polling connection open, answers Engine.IO pings, reads configured power once through ODB ID `20`, and reads displayed target temperature, current water consumption and current power consumption every 600 seconds by default through ODB IDs `0`, `15` and `16`.

Temperature writes use ODB ID `66` with readback through ODB ID `0`.
