# Stiebel DHE Connect für Home Assistant

Custom Integration für Stiebel-Eltron-DHE-Connect-Durchlauferhitzer über die lokale Socket.IO-/Engine.IO-v3-Long-Polling-Schnittstelle.

Die Integration ist für den Betrieb im lokalen Heimnetz gedacht. Sie stellt eine `climate`-Entität bereit, über die die Anzeige-/Solltemperatur des DHE gesetzt und gelesen wird.

## Status

Experimentelle Custom Integration. Getestet gegen einen lokal erreichbaren DHE Connect auf Port `8443`.

## Funktionsumfang

- Konfiguration über die Home-Assistant-Oberfläche, kein YAML erforderlich.
- IP/Hostname, Port, Entitätsname und Werte-Polling-Intervall konfigurierbar.
- Lokaler Betrieb ohne Cloud.
- Token wird lokal in Home Assistant gespeichert.
- Nach dem HA-Start wird eine Socket.IO-/Engine.IO-Long-Polling-Session dauerhaft offen gehalten.
- Die Integration antwortet auf Engine.IO-Pings und reconnectet automatisch, falls der DHE die Session schließt.
- ODB ID `0` wird im konfigurierten Intervall gelesen, Standard `600` Sekunden.
- Bei einer Temperaturänderung wird über die bestehende Session ODB ID `66` geschrieben und ODB ID `0` als Readback gelesen.
- Die Entität bleibt sichtbar; die Verfügbarkeit ergibt sich aus der persistenten DHE-Session, nicht mehr aus einem separaten HTTP-Ping.

## Verwendete ODB-IDs

| Zweck | Befehl | ODB ID |
|---|---|---:|
| Anzeige-/Solltemperatur lesen | `get:ste.common.odb:value` | `0` |
| Anzeige-/Solltemperatur setzen | `assign:ste.common.odb:value` | `66` |

Die Temperatur wird in Zehntelgrad übertragen, also z. B. `345` für `34,5 °C`. Das Setzen über ID `66` nutzt zusätzlich die vom Web-UI bekannte Request-Adressierung in den oberen Bits.


## Repository-Upload nach GitHub

Das Repository ist für diese URL vorbereitet:

```text
https://github.com/memphi2/ha-dhe-connect
```

Minimaler Upload:

```bash
git clone https://github.com/memphi2/ha-dhe-connect.git
cd ha-dhe-connect
# Inhalt dieses ZIPs in diesen Ordner kopieren
git add .
git commit -m "Initial HACS custom integration"
git push origin main
```

Optionaler Release-Tag für HACS:

```bash
git tag v0.4.1
git push origin v0.4.1
```

## Installation über HACS als Custom Repository

1. Dieses Repository in GitHub anlegen, `ha-dhe-connect`.
2. Den Inhalt dieses ZIPs ins Repository legen. Die Struktur muss so aussehen:

```text
hacs.json
README.md
custom_components/
  stiebel_dhe_connect/
    __init__.py
    manifest.json
    config_flow.py
    client.py
    climate.py
    const.py
    strings.json
```

3. In HACS öffnen:

```text
HACS → Integrationen → Drei Punkte → Benutzerdefinierte Repositorys
```

4. Repository-URL `https://github.com/memphi2/ha-dhe-connect` eintragen und Kategorie `Integration` wählen.
5. Integration installieren.
6. Home Assistant neu starten.
7. Hinzufügen über:

```text
Einstellungen → Geräte & Dienste → Integration hinzufügen → Stiebel DHE Connect
```

## Manuelle Installation

Alternativ den Ordner kopieren nach:

```text
/config/custom_components/stiebel_dhe_connect/
```

Danach Home Assistant neu starten und die Integration über die Oberfläche hinzufügen.

## Konfiguration

Über die HA-Oberfläche werden abgefragt:

| Feld | Bedeutung | Beispiel |
|---|---|---|
| IP-Adresse oder Hostname | Adresse des DHE im lokalen Netz | `172.16.2.124` |
| Port | HTTP-/Socket.IO-Port | `8443` |
| Name der Entität | Anzeigename in HA | `DHE Connect` |
| Werte-Polling | Leseintervall für ODB ID `0` in Sekunden | `600` |

Eingaben werden validiert: Host darf nur IP-Adresse oder Hostname sein; Pfade, Benutzerinformationen, Query-Strings und eingebettete Ports werden abgewiesen. Der Port muss zwischen `1` und `65535` liegen. Das Werte-Polling muss zwischen `60` und `86400` Sekunden liegen.

## Pairing und Token

Beim ersten Zugriff kann der DHE ein Pairing verlangen. In diesem Fall am DHE bestätigen.

Der Token wird lokal gespeichert unter:

```text
/config/.storage/stiebel_dhe_connect_token.txt
```

Zum Neu-Pairing diese Datei löschen und Home Assistant neu starten oder die Integration neu laden.

## Verhalten der Verbindung

Die Integration hält ab v0.4.0 eine dauerhafte Socket.IO-/Engine.IO-v3-Long-Polling-Session offen. Das ist für dieses Gerät wichtig, weil Engine.IO bei längerer Inaktivität eigene Ping/Pong-Frames erwartet.

- Beim Start: Session öffnen, Token prüfen/refreshen, authentifizieren.
- Laufend: Long-Polling-GETs offen halten und Engine.IO-Pings beantworten.
- Alle konfigurierten `poll_interval` Sekunden: ODB ID `0` lesen.
- Bei Änderung der Zieltemperatur: über dieselbe Session ODB ID `66` schreiben und ODB ID `0` als Readback lesen.
- Bei Session-Close: Entity kurz unavailable, automatischer Reconnect.

## Sicherheitshinweise

- Die Integration sollte nur in einem vertrauenswürdigen lokalen Netzwerk eingesetzt werden.
- Den Port `8443` des DHE nicht ins Internet weiterleiten.
- Der Token liegt lokal in der HA-Konfiguration. Die Integration setzt beim Speichern nach Möglichkeit Dateirechte `0600`; die tatsächliche Durchsetzung hängt vom HA-Dateisystem ab.
- Token werden nicht bewusst ins Log geschrieben. Debug-Rohdaten sollten trotzdem nicht öffentlich geteilt werden.
- Die Integration nutzt HTTP zur lokalen DHE-Weboberfläche, weil das Gerät diese lokale Schnittstelle so bereitstellt.
- Die Integration beschränkt die einstellbare Temperatur auf `20,0 °C` bis `60,0 °C` und rundet auf `0,5 °C`.

## Debugging

Home-Assistant-Log prüfen:

```text
Einstellungen → System → Protokolle
```

Typische Probleme:

| Symptom | Ursache / Lösung |
|---|---|
| Integration nicht verfügbar | IP/Port prüfen, DHE-Weboberfläche im Browser testen |
| Pairing kommt immer wieder | Token-Datei löschen und einmal neu pairen |
| Schreiben klappt nicht | Prüfen, ob DHE lokal über Port `8443` erreichbar ist |
| Temperatur ändert sich nicht | DHE-Grenzen, Sperren oder Gerätemodus prüfen |

## Release Notes

### v0.4.1

- Repository-Metadaten auf `memphi2/ha-dhe-connect` angepasst.
- Manifest-Links und Code Owner gesetzt.
- Dokumentation für GitHub-/HACS-Veröffentlichung ergänzt.

### v0.4.0

- Verbindung wird jetzt persistent offen gehalten.
- HTTP-Ping entfernt; stattdessen wird ODB ID `0` im konfigurierten Intervall gepollt.
- Engine.IO-Ping/Pong für dauerhafte Long-Polling-Session ergänzt.
- Schreiben läuft über die bestehende Session und wartet auf passendes Readback.
- Config-Option von `ping_interval` auf `poll_interval` umgestellt; alte Einträge bleiben kompatibel.

### v0.3.0

- Sicherheits- und Robustheitsreview.
- Host-/Port-/Intervall-Validierung verschärft.
- Token-Speicherung atomar gemacht; Dateirechte nach Möglichkeit auf User-only gesetzt.
- Keine Token-Ausgabe in normalen Logs.
- Startup-Read auf genau eine Socket.IO-Session reduziert.
- Write-Retry von 3 auf 2 Versuche reduziert, damit keine unnötigen Schreibsessions entstehen.
- Device-Info für Home Assistant ergänzt.
- Dokumentation um Sicherheitskapitel ergänzt.

### v0.2.1

- HACS-kompatible Repository-Struktur ergänzt.
- Root-README, `hacs.json` und Lizenz ergänzt.
- Dokumentation für Installation, Pairing, Konfiguration und Betriebsverhalten ergänzt.

### v0.2.0

- Config Flow/UI-Konfiguration.
- Keine dauerhafte Socket.IO-Verbindung.
- Einmaliges Lesen beim Start, Lesen nach Änderung, Verfügbarkeits-Ping alle 600 Sekunden. *(bis v0.3.x)*


## Startup behavior

The persistent polling session runs as a Home Assistant background task and should not block HA startup.
