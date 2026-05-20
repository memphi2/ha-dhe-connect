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
| DHE Connect 18/21/24 | `1.9.00` observed | yes | Pairing, setup flow, runtime connection, climate, live water/power sensors, timers, radio, weather, recorder smoke, diagnostics | Primary live validation target for the current release line |
| DHE Connect 27 | unknown | planned | Not yet validated on a dedicated live device | Expected to share most protocol behavior, but needs confirmation before marking as partial or yes |

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
