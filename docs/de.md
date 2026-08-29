# Deutsche Kurzanleitung

Kurzfassung fuer Installation und Betrieb der inoffiziellen DHE-Connect
Integration in Home Assistant.

Die Detaildokumentation bleibt in den englischen Seiten:

- [Entitaeten](entities.md)
- [Troubleshooting](troubleshooting.md)
- [Validierung](validation.md)
- [Protokoll](protocol.md)

## Installation (HACS)

[![DHE Connect direkt in HACS oeffnen](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=memphi2&repository=ha-dhe-connect&category=integration)

1. HACS -> `Integrations`
2. Nach `DHE Connect` suchen
3. Repository oeffnen und `Download` auswaehlen
4. Home Assistant neu starten
5. Integration unter `Einstellungen -> Geraete & Dienste` hinzufuegen

`DHE Connect` ist im HACS-Standardkatalog enthalten. Das Hinzufuegen als
benutzerdefiniertes Repository ist nicht mehr erforderlich. Bereits auf diesem
Weg installierte Versionen erhalten weiterhin Updates und muessen nicht neu
installiert werden.

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

Das DHE-Pairing-Token wird im Home-Assistant-Config-Entry gespeichert. Alte
zielbezogene Token-Dateien aus frueheren Versionen werden automatisch in den
Config Entry uebernommen und danach geloescht.

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
