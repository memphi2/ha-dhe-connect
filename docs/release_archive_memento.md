# Release Archive Memento

Kurzfassung der aktuellen Release-Notizen in kompaktem Changelog-Format.

## v1.8.1 - 2026-05-21
- Patch-Release-Vorbereitung fuer die v1.8-Linie mit stabilen Entity-IDs,
  Unique-IDs und unveraenderter DHE-Protokollsemantik.
- Zeroconf-Geraetenamen, Diagnostics-Export und Firmware-Matrix-Hinweise
  bereinigt.
- Security-/Privacy-Hygiene ergaenzt: IPv6-Redaction, hostfreie
  Pairing-Notification-IDs und breiterer Deprecation-Guard fuer Code, CI und
  Doku.

## v1.8.0 - 2026-05-21
- Gold-/Platinum-nahes Finalisierungslauf: striktere Typ-Härtung,
  Diagnostics-/Error-Handling-Stabilisierung und weitere Quality-Scale-Anpassungen.
- README- und Release-Hygiene vereinheitlicht, einschließlich badge-basierter
  Release-Sichtprüfung.
- Reconnect-/Repair-/Reconfigure-Cases weiter konsolidiert, bestehende Entity- und
  Device-IDs stabil gehalten.

## v1.7.0 - 2026-05-21
- Stabilisierung von Repair-Flow und Reconfigure-Flow mit Fokus auf
  nutzerseitige Auflösungsketten ohne neue DHE-Features.
- QA- und Release-Dokumentation nach v1.6.x konsolidiert.
- Qualitätstransparenz via `quality_scale.yaml` und Testabdeckung aufgeräumt.

## v1.6.0 - 2026-05-20
- Initiale stabile Veröffentlichung mit grundsätzlicher DHE-Integration,
  Websocket/Runtime-Pfad und vollständiger Basistestsuite.
