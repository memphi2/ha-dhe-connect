# Stiebel Eltron DHE Connect: Kurzanleitung

Inoffizielle Community-Integration fuer die lokale Anbindung kompatibler
Stiebel-Eltron-DHE-Connect-Geraete. Das Icon ist eigenes Projekt-Artwork,
nicht das Herstellerlogo.

## Voraussetzungen

- Home Assistant `2026.10.4` oder neuer. Fuer HA `2026.10.1` bis `2026.10.3`
  Integrationsversion `v2.0.9` verwenden; fuer noch aeltere HA-Versionen eine
  Veroeffentlichung mit passender Mindestversion waehlen.
- Das DHE-Webinterface ist aus dem Home-Assistant-Netz erreichbar.
- Zugriff auf das DHE-Display fuer die Pairing-Bestaetigung.

## Installation im Marketplace

Ab HA 2026.11. Unter HA 2026.10 **Stiebel Eltron DHE Connect** in HACS
installieren, Home Assistant neu starten und mit Schritt 4 fortfahren.
Updates unter dieser Version ebenfalls ueber HACS beziehen.

1. `Einstellungen` -> `Marketplace` oeffnen.
2. Nach `DHE Connect` suchen und **Stiebel Eltron DHE Connect** waehlen.
3. Integration installieren und den Hinweis zur Community-Integration bestaetigen.
4. Unter `Einstellungen` -> `Geraete & Dienste` die Integration hinzufuegen.
5. Gefundenes Geraet waehlen, Subnetz scannen oder Host und Port manuell angeben.
6. Pairing am DHE-Display bestaetigen, wenn die Einrichtung dazu auffordert.

Kein benutzerdefiniertes Repository erforderlich. Eine erste Marketplace-
Installation braucht normalerweise keinen HA-Neustart. Nach Updates oder dem
Entfernen geladenen Codes der Neustartaufforderung von Home Assistant folgen.

Die vollstaendige [Installationsanleitung](installation.md) beschreibt auch
Updates, manuelle Installation und Entfernung. Die Metadatendatei heisst
weiterhin `hacs.json`; sie wird auch vom Marketplace verwendet.

## Bestehende Installationen und Updates

Der Anzeigename lautet **Stiebel Eltron DHE Connect**, der Hersteller in den
Geraeteinformationen **Stiebel Eltron**. Die Domain bleibt
`stiebel_dhe_connect`. Bestehende Config Entries, Entity-IDs, Geraete-IDs,
Tokens und selbst vergebene Namen bleiben erhalten.

Bereits ueber HACS installierte Versionen verwenden dasselbe Repository und
dieselbe Domain. Nicht loeschen, neu installieren oder ein zweites Exemplar
daneben anlegen. Den vorhandenen Updateweg nutzen und bestehende Eintraege
behalten; fuer diese Umbenennung ist kein neues Pairing erforderlich.

Marketplace-Updates stehen unter `Einstellungen` -> `Updates`. Vor einem Update
ein HA-Backup anlegen, die Release-Hinweise lesen und danach den angeforderten
HA-Neustart abschliessen. Ein manuell kopierter Entwicklungsstand ist keine
veroeffentlichte Marketplace-Version.

## Einrichtung und Pairing

Der Einrichtungsdialog bietet Zeroconf-Discovery (`_ste-dhe._tcp.local.`),
Subnetz-Scan im privaten IPv4-Netz und manuelle Host-/Port-Eingabe. Zeroconf
braucht mDNS-Sichtbarkeit im lokalen Netz oder ein passend eingerichtetes Relay.
Beim Host nur Hostname oder IP-Adresse eingeben, keine URL oder Portangabe.
Der Standardport ist `8443`.

Ein Config Entry wird erst nach erfolgreichem Pairing und Login angelegt.
Das Token liegt im Home-Assistant-Config-Entry. Alte Token-Dateien werden bei
der Migration uebernommen und danach geloescht. `.storage` nicht von Hand aendern.

Bei einem abgelehnten Token zuerst das passende Problem unter
`Einstellungen` -> `System` -> `Reparaturen` bearbeiten. Falls kein Problem
sichtbar ist, den standardmaessig deaktivierten Button `Repair pairing`
aktivieren und verwenden. Das neue Pairing am DHE bestaetigen.

Bei einer geaenderten Adresse `Neu konfigurieren` am bestehenden Eintrag nutzen,
nicht einen weiteren Eintrag fuer dasselbe Geraet anlegen.

## Betrieb und Hilfe

- Live-Werte und Steuerung laufen lokal ueber Socket.IO/Engine.IO.
- Optionale Diagnose- und haeufig wechselnde Entitaeten nur bei Bedarf aktivieren.
- Bei mehreren DHE-Geraeten Integrationsaktionen mit `entry_id` zuordnen.
- Bei Problemen [Troubleshooting](troubleshooting.md) nutzen und bestehende
  Eintraege nicht vorsorglich loeschen.

## Entfernung und Sicherheit

Zuerst die betroffenen Config Entries unter `Geraete & Dienste` entfernen.
Danach bei Bedarf die Integration im Marketplace deinstallieren und den
angeforderten Neustart abschliessen. Bei HACS- oder manuellen Installationen
die [Entfernungsanleitung](installation.md#removal) beachten.

Nur im vertrauenswuerdigen lokalen Netz einsetzen; das DHE-Webinterface nicht
ins Internet freigeben. Keine Tokens, privaten Hosts, IPs oder ungekuerzten
Speicherdateien in Issues veroeffentlichen. Das Entfernen eines HA-Tokens
widerruft nicht automatisch seine Berechtigung am DHE.

## Weitere Dokumentation

- [Entitaeten und Aktionen](entities.md)
- [Automationsbeispiele](examples.md)
- [Bekannte Grenzen](known_limitations.md)
- [Sicherheit](../SECURITY.md)
- [Rechtliches und eigene Grafiken](legal.md)
- [Validierung fuer Entwicklung und Maintainer](validation.md)
