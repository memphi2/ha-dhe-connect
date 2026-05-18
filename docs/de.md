# Deutsche Kurzanleitung

Diese Seite ist eine deutschsprachige Einstiegshilfe fuer Installation, Pairing,
Betrieb und Fehlersuche der Stiebel DHE Connect Integration. Die detaillierten
technischen Tabellen bleiben in den englischen Dokumenten:

- [Entitaeten, Attribute und Services](entities.md)
- [Troubleshooting](troubleshooting.md)
- [Protokoll- und ODB-Notizen](protocol.md)
- [Validierung und Release-Checks](validation.md)

## Was die Integration macht

Die Integration verbindet Home Assistant direkt mit dem lokalen Webinterface
eines DHE Connect Durchlauferhitzers. Es wird kein Cloud-Dienst verwendet. Home
Assistant baut eine lokale Socket.IO / Engine.IO Verbindung zum Geraet auf,
authentifiziert sich mit einem Pairing-Token und haelt danach eine laufende
Runtime-Verbindung fuer Messwerte, Status und Befehle.

Typische Funktionen:

- Zieltemperatur als Climate-Entitaet mit `heat` und `off`.
- Aktueller Wasserfluss und aktuelle Leistung fuer Live-Dashboards.
- Verbrauchs- und Sparmonitor-Werte, zum Teil bewusst deaktiviert.
- Temperatur-Speicherplaetze, Eco, Badewannenfuellung, Timer und Wellness.
- Radio-Player mit Favoriten und Quellenauswahl.
- Wetter-Favoriten aus dem DHE-Webinterface.
- Diagnosewerte fuer Verbindung, Reconnects, naechste Retry-Verzoegerung,
  Fehlerstatus und Protokoll.

## Installation ueber HACS

1. HACS oeffnen.
2. `Integrations` waehlen.
3. Im Drei-Punkte-Menue `Custom repositories` oeffnen.
4. Repository eintragen:

   ```text
   https://github.com/memphi2/ha-dhe-connect
   ```

5. Kategorie `Integration` auswaehlen.
6. `Stiebel DHE Connect` installieren.
7. Home Assistant neu starten.
8. Unter `Einstellungen` -> `Geraete & Dienste` die Integration hinzufuegen.

## Manuelle Installation

Den Integrationsordner nach Home Assistant kopieren:

```text
/config/custom_components/stiebel_dhe_connect/
```

Danach Home Assistant neu starten und die Integration ueber die UI hinzufuegen.

## Einrichtung und Pairing

Beim Hinzufuegen zeigt Home Assistant zuerst einen Einrichtungsweg:

- gefundene DHE-Connect-Geraete aus Zeroconf/mDNS, wenn Home Assistant die
  `_ste-dhe._tcp.local.`-Ankuendigung sieht,
- `Subnetz-Scan` fuer die Suche nach DHE-aehnlichen Webinterfaces. Der
  Scan-Port ist mit `8443` vorbelegt,
- `Manuell eingeben` fuer direkte Host/IP-Eingabe.

Die Subnetzfelder erscheinen nur nach Auswahl von `Subnetz-Scan`. Der Scan kann
das aktuelle lokale Subnetz verwenden, Netzwerkadresse plus Subnetzmaske
abfragen, zum Beispiel `192.168.1.0` und `255.255.255.0`, oder CIDR-Schreibweise
wie `192.168.1.0/24` akzeptieren. Home Assistant belegt die benutzerdefinierten
Subnetzfelder nach Moeglichkeit mit dem aktuellen lokalen Subnetz vor. Wenn ein
Kandidat gefunden wird, oeffnet die normale Maske mit vorbelegtem Host und Port.
Wenn nichts gefunden wird, oeffnet dieselbe Maske fuer manuelle Eingabe.

Den Scan-Port nur aendern, wenn das DHE-Webinterface nicht auf `8443` laeuft.
Der Scan-Port gilt nur fuer den Einrichtungs-Scan; Zeroconf und manuelle
Einrichtung verwenden den gemeldeten oder eingegebenen Port des Ziels.

Zeroconf/mDNS funktioniert normalerweise nur im lokalen Subnetz/VLAN.
Subnetzuebergreifende Erkennung braucht einen Router oder eine Firewall mit
mDNS-Reflector oder Repeater. Eine direkte `.local`-Namensaufloesung oder eine
Unicast-DNS-SD-Antwort des DHE reicht fuer den Home-Assistant-Zeroconf-Flow
nicht aus; Home Assistant muss die Multicast-Ankuendigung empfangen. Wenn das
DHE per IP erreichbar ist, aber nicht automatisch auftaucht, manuell einrichten
oder den expliziten Subnetz-Scan verwenden.

Vor einem Release sollte der optionale echte Zeroconf/mDNS-Smoke aus dem
Release-Lab-Netz laufen, in dem Home Assistant die DHE-Ankuendigung sehen soll:

```bash
python scripts/zeroconf_smoke.py --timeout 20
```

Das ist kein universeller CI-Check. Der Test haengt von lokaler
Multicast-Sichtbarkeit ab und kann in VLAN- oder Firewall-Setups scheitern,
obwohl der Integrationscode korrekt ist.

Die UI fragt nach:

| Feld | Beispiel | Hinweis |
|---|---|---|
| Host | `dhe.local` | Nur Hostname oder IP, keine URL mit Pfad |
| Port | `8443` | Port des lokalen DHE-Webinterfaces |
| Geraetename | `DHE Connect` | Name in Home Assistant |
| Interner Verbruehschutz | `60` | Physische `Tmax`-Jumper-Position |

Der erste Verbindungsaufbau erstellt den Home-Assistant-Eintrag erst nach einem
erfolgreichen Pairing:

1. Daten im Config Flow eingeben.
2. Pairing-Bestaetigungsseite in Home Assistant bestaetigen.
3. Pairing am DHE-Display bestaetigen.
4. Warten, bis Home Assistant den Eintrag erstellt.

Der Token wird danach lokal in der Home-Assistant-Konfiguration gespeichert.
Bei mehreren DHE-Geraeten bekommt jedes Host/Port-Ziel einen eigenen Token.
Zeroconf, Subnetz-Scan und manuelle Einrichtung nutzen denselben
Pairing-Bestaetigungsweg. Wenn das DHE beim Pairing eine MAC-Adresse liefert,
wird sie als stabile Unique-ID des Config-Eintrags verwendet.

## Mehrere DHE-Geraete

Fuer jedes DHE-Geraet wird ein eigener Integrations-Eintrag angelegt. Wichtig:

- Host und Port duerfen pro Eintrag nur einmal vorkommen.
- Services sollten bei mehreren Geraeten immer mit `entry_id` aufgerufen werden.
- Jedes Geraet hat eigene Entitaeten, eigene Runtime-Verbindung und eigenen
  Pairing-Token.

## Wichtige Entitaeten

Standardmaessig sichtbar sind die wichtigsten Betriebswerte, unter anderem:

- Climate-Zieltemperatur.
- Aktueller Wasserfluss.
- Aktuelle Leistung.
- Gesamt-Wasserverbrauch.
- Gesamt-Heizenergie.
- Wetter- und Radio-Basisentitaeten.
- Diagnosewerte fuer Verbindung, Reconnects und naechsten Reconnect-Versuch.

Weitere Entitaeten sind absichtlich deaktiviert, damit Home Assistant und der
Recorder nicht unnoetig viele Werte schreiben. Dazu gehoeren viele Diagnose-,
Timer-, Sparmonitor- und Protokollwerte. Diese Entitaeten koennen bei Bedarf in
der Home-Assistant-UI aktiviert werden.

Die vollstaendige Liste steht in [docs/entities.md](entities.md).

## Wasser- und Energie-Dashboard

Wasserverbrauchswerte werden als echte Home-Assistant-Wassermeter angelegt,
soweit die jeweilige Entitaet dafuer geeignet ist. Nach dem Aktivieren einer
neuen Verbrauchsentitaet kann Home Assistant etwas Zeit brauchen, bis sie in
Dashboard-Auswahllisten erscheint.

Wenn ein Wert nach dem Start noch nie vom DHE gesendet wurde, kann er
zunaechst `unknown` sein. Das ist besser als ein falscher Nullwert. Sobald das
DHE den Wert real sendet, uebernimmt die Integration den Runtime-Wert.

## Recorder und Datenbank

Die Integration filtert und drosselt bekannte High-Churn-Werte, damit die
Home-Assistant-Datenbank nicht unnoetig waechst. Besonders wichtig:

- Grosse Radio-, Wetter- und Suchlisten werden nicht dauerhaft als
  recorder-relevante Attribute geschrieben.
- Aktueller Wasserfluss und aktuelle Leistung bleiben live sichtbar: Aenderungen
  ab `0.2` sowie Wechsel zwischen `0` und einem aktiven Wert werden geschrieben.
- Timer-Restzeiten und Wannenfuellmengen werden nicht gedrosselt, damit sie in
  der UI live bleiben.
- Bei Wasserlauf, Duschtimer- oder letzter-Nutzung-Fenstern kann es erwartbar
  mehr Recorder-Aktivitaet geben.

Home Assistant schreibt normale State-Aenderungen in den Recorder, solange die
betroffenen Entitaeten dort nicht ausgeschlossen sind. Live-Anzeige ohne
Recorder-Historie muss deshalb ueber die Home-Assistant-Recorder-Konfiguration
mit konkreten Entity-IDs geloest werden. Das gilt auch fuer optionale
Timer-Restzeiten und Wannenfuellmengen, wenn sie zwar live sichtbar sein, aber
nicht dauerhaft in der Datenbank landen sollen.

Beispiel, angepasst auf die tatsaechlichen Entity-IDs in der eigenen
Home-Assistant-Installation:

```yaml
recorder:
  exclude:
    entities:
      - sensor.dhe_connect_water_flow
      - sensor.dhe_connect_power
      - sensor.dhe_connect_shower_timer_remaining
      - sensor.dhe_connect_brush_timer_remaining
      - sensor.dhe_connect_bath_fill_remaining_volume
      - sensor.dhe_connect_bath_fill_current_volume
```

Wenn die Datenbank trotzdem stark waechst, zuerst die Diagnose-Entitaeten,
Reconnect-Zaehler und Home-Assistant-Logs pruefen. Details stehen in
[docs/troubleshooting.md](troubleshooting.md).

Kurze Verbindungsabbrueche bleiben in einer Reconnect-Schonfrist: gecachte
Entitaeten koennen verfuegbar bleiben, waehrend der Diagnosewert
`Verbindungsstatus` bereits `Verbindet neu` zeigt. Erst nach Ablauf dieser
Schonfrist werden Live-Entitaeten unavailable, bis wieder frische DHE-Daten
ankommen.

## Pairing reparieren

Wenn Pairing oder Token nicht mehr passen:

1. Die deaktivierte Entitaet `Repair pairing` aktivieren.
2. Den Button ausfuehren.
3. Pairing am DHE bestaetigen.

Der Button loescht den lokalen Token und startet eine neue Pairing-Runde. Nach
mehreren fehlgeschlagenen Versuchen pausiert die Integration automatische
Retries, damit das System nicht endlos reconnectet. Danach erneut den Button
ausloesen, wenn das DHE bereit ist.

## Radio- und Wetterfunktionen

Radio und Wetter nutzen die Daten, die das DHE-Webinterface bereitstellt.
Favoriten und Quellen sollten ueber die Optionen oder Services der Integration
verwaltet werden. Bei mehreren DHE-Geraeten immer `entry_id` angeben, damit der
Service das richtige Geraet trifft.

Bei Smoke-Tests kann der Radio-Service kurz eine Quelle auswaehlen. Der
Test-Helper schaltet das Radio danach automatisch wieder aus.

## Sicherheit

- Nur in einem vertrauenswuerdigen lokalen Netzwerk verwenden.
- Das DHE-Webinterface und Port `8443` nicht ins Internet freigeben.
- Home-Assistant-Backups und gemountete Konfigurationsordner als sensibel
  behandeln, weil sie Tokens enthalten koennen.
- Logs, Smoke-Tests und Diagnosehilfen sollen Tokens, Zugangsdaten und private
  Host-Kontexte redigieren.

Siehe auch [SECURITY.md](../SECURITY.md).

## Rechtliche Hinweise

Dieses Projekt ist eine inoffizielle Community-Integration. Es ist nicht mit
STIEBEL ELTRON, Home Assistant oder HACS verbunden, nicht von diesen
unterstuetzt und nicht gesponsert.

Produkt- und Projektnamen werden nur zur Beschreibung der Kompatibilitaet
verwendet. Die mitgelieferten PNG-Bilder unter `brand/` sind originale
Projektgrafiken und enthalten keine kopierten Herstellerlogos oder Produktmarken.

Code, Dokumentation und mitgelieferte Projektgrafiken stehen, soweit nicht
anders angegeben, unter der MIT-Lizenz. Diese Lizenz erteilt keine Rechte an
Drittmarken, Geraete-Firmware, Hersteller-Webinterfaces oder anderen
Drittinhalten.

## Wenn etwas nicht funktioniert

| Symptom | Erster Check |
|---|---|
| Integration verbindet nicht | DHE im Browser unter `http://<host>:<port>/` pruefen |
| Pairing wiederholt sich | `Repair pairing` aktivieren und ausfuehren |
| Entitaeten bleiben unavailable | Diagnose-Entitaeten und HA-Logs pruefen |
| Reconnect-Zaehler steigt | WebSocket-Verbindung und zweite Clients pruefen |
| Service trifft falsches Geraet | `entry_id` im Service-Aufruf setzen |
| Recorder schreibt zu viel | Wasserlauf-/Nutzungsfenster und High-Churn-Entitaeten pruefen |

Mehr Details: [docs/troubleshooting.md](troubleshooting.md).
