# Stiebel DHE Connect

Lokale Home-Assistant-Integration für Stiebel-Eltron-DHE-Connect-Geräte.

Repository: `memphi2/ha-dhe-connect`.

Diese Version hält eine Socket.IO-/Engine.IO-v3-Long-Polling-Verbindung offen, beantwortet Engine.IO-Pings und liest die Anzeige-/Solltemperatur standardmäßig alle 600 Sekunden über ODB ID `0`.

Setzen erfolgt über ODB ID `66` mit anschließendem Readback über ODB ID `0`.
