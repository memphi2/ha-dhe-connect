# Device And Firmware Matrix

This matrix tracks which DHE Connect device and firmware combinations have been
validated with the integration. It is intentionally conservative: only add a
combination as tested when it has passed a real Home Assistant setup or smoke
run against that device family.

Do not add private data to this file. Keep hosts, IP addresses, MAC addresses,
serial numbers, pairing tokens and full product IDs out of the matrix. The Home
Assistant UI can show the full product ID for the local user, but public reports
and anonymized diagnostics should only use the first 7 characters.

## Status Meanings

| Status | Meaning |
|---|---|
| `yes` | Confirmed with a real device and the current integration validation flow |
| `partial` | Basic protocol behavior is confirmed, but not every feature was tested on that device/firmware combination |
| `planned` | Known or expected device family, but no current live validation evidence yet |
| `unknown` | Reported by a user without enough evidence to classify |

## Matrix

| Device | Firmware / Web-App Version | Tested | Coverage | Notes |
|---|---|---|---|---|
| DHE Connect 18/21/24 | `1.9.00` observed | yes | Pairing, setup flow, runtime connection, climate, live water/power sensors, timers, ODB ID `32` wellness runtime, radio, weather, recorder smoke, diagnostics | Primary live validation target for the current release line; latest full live evidence run: `2026-05-21` |
| DHE Connect 27 | unknown | planned | Not yet validated on a dedicated live device | Expected to share most protocol behavior, but needs confirmation before marking as partial or yes |

## Required Evidence Fields

For every new or changed matrix row, capture at least:

1. Device family (for example `DHE Connect 18/21/24`).
2. Firmware or web-app version reported by the device.
3. Validation date (`YYYY-MM-DD`).
4. Integration branch/tag that was tested.
5. Result status (`yes`, `partial`, `planned`, `unknown`).
6. Coverage scope:
   - setup/pairing
   - reconnect/offline recovery
   - climate and live water/power
   - at least one timer path
   - optional feature groups (radio/weather/savings) when relevant
7. Non-private notes on limitations or deviations.

Do not include private infrastructure data (IPs, hostnames, MACs, tokens,
serial numbers, full product IDs).

## Evidence Entry Template

Use this template for reproducible evidence entries in issue comments, PR notes
or release prep notes:

```text
Device family: DHE Connect 18/21/24
Firmware/web-app: 1.9.00
Validation date: 2026-05-21
Branch/tag: v1.8.0
Result: yes
Coverage:
- setup/pairing: pass
- reconnect/offline recovery: pass
- climate + live water/power: pass
- timer path: pass
- optional features: radio pass, weather pass, savings n/a
Notes:
- No private host/token data included
```

## Current Evidence Snapshot

This section summarizes the currently documented live evidence level and keeps
the matrix interpretation conservative:

- `DHE Connect 18/21/24` has repeated live validation evidence with
  `1.9.00`-observed web interface behavior.
- Additional families (for example `DHE Connect 27`) remain `planned` until
  direct evidence is recorded using the template above.

### Latest Recorded Live Evidence

- Date: `2026-05-21`
- Device family: `DHE Connect 18/21/24`
- Firmware/web-app: `1.9.00` observed
- Scope:
  - setup/pairing
  - repairs/reauth recovery
  - reconnect/offline recovery
  - climate + live water/power
  - timers
  - ODB ID `32` wellness runtime counter
  - radio/weather runtime behavior
- Result: pass for release-prep scope on the current integration line.

## How To Add A Result

1. Open the DHE web interface and note the firmware or web-app version shown by
   the device. The integration also exposes the web-app/protocol version through
   diagnostics and the protocol-version entity when available.
2. Run the normal repository checks and at least one Home Assistant smoke run
   against the device.
3. Verify pairing, reconnect behavior, climate control, current water flow,
   current power, at least one timer path and the affected optional feature
   group if the test is meant to cover radio, weather or saving-monitor values.
4. Add a row with the device family, firmware/web-app version, test status,
   coverage summary and any relevant non-private notes.

Recommended validation commands are listed in
[validation.md](validation.md). Network-specific Zeroconf results should be
recorded only as feature coverage, not as proof that every network layout will
discover the device automatically.
