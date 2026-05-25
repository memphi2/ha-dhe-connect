# Deutsche Kurzanleitung

Kurzfassung fuer Installation und Betrieb der inoffiziellen DHE-Connect
Integration in Home Assistant.

Die Detaildokumentation bleibt in den englischen Seiten:

- [Entitaeten](entities.md)
- [Troubleshooting](troubleshooting.md)
- [Validierung](validation.md)
- [Protokoll](protocol.md)

## Installation (HACS)

1. HACS -> `Integrations`
2. `Custom repositories`
3. Repository URL:

   ```text
   https://github.com/memphi2/ha-dhe-connect
   ```

4. Kategorie `Integration`
5. `DHE Connect` installieren
6. Home Assistant neu starten
7. Integration in `Einstellungen -> Geraete & Dienste` hinzufuegen

## Manuelle Installation

Nach:

```text
/config/custom_components/stiebel_dhe_connect/
```

kopieren, Home Assistant neu starten, Integration ueber UI hinzufuegen.

## Setup

Der Setup-Flow bietet:

- Zeroconf discovery (`_ste-dhe._tcp.local.`)
- Subnetz-Scan (private IPv4, Standardport `8443`)
- Manuelle Host/Port-Eingabe

Hinweis: Zeroconf funktioniert normalerweise nur im lokalen Subnetz/VLAN, wenn
kein mDNS-Relay aktiv ist.

## Pairing und Token

Der Config Entry wird erst nach erfolgreichem Pairing angelegt.

Token-Datei pro DHE-Ziel:

```text
/config/.storage/stiebel_dhe_connect_token_<host>_<port>.txt
```

Bei Token-/Pairing-Problemen zuerst den deaktivierten `Repair pairing` Button
aktivieren und nutzen.

## Betrieb

- Live-Werte und Steuerung laufen lokal ueber Socket.IO/Engine.IO.
- Einige Diagnose- und High-Churn-Entitaeten sind bewusst standardmaessig
  deaktiviert.
- Bei mehreren DHE-Geraeten Services immer mit `entry_id` aufrufen.

## Troubleshooting

Startpunkt immer:

- [Troubleshooting](troubleshooting.md)

Typische Themen:

- Pairing/Token ungültig
- DHE offline/reconnecting
- Zeroconf findet nichts
- Recorder schreibt zu viele Daten

## Sicherheit und Rechtliches

- Nur im vertrauenswuerdigen lokalen Netz einsetzen.
- DHE-Webinterface nicht ins Internet freigeben.
- Keine Tokens/Hosts/private IPs in Issues, PRs oder Release-Texten veroeffentlichen.

Siehe:

- [SECURITY.md](../SECURITY.md)
- [Legal](legal.md)
