# DHE Protocol Reference

This document captures observed local interoperability behavior for compatible
DHE Connect devices and the Home Assistant integration.

It is intentionally limited to protocol identifiers, payload shapes and observed
behavior needed for interoperability. It does not include vendor web assets,
templates or copied implementation code.

The protocol is intentionally treated as an implementation detail. Use the Home Assistant entities and services for normal automation; use this reference when maintaining the integration, debugging device traffic or extending the ODB mapping.

Protocol names in this document are not necessarily Home Assistant display
names. User-facing names are kept in the translation files and summarized in
[entities.md](entities.md); this file keeps raw command names, ODB IDs and
observed web-interface labels.

## Transport Overview

The DHE web UI uses Socket.IO over Engine.IO v3. The integration mirrors that behavior closely:

1. Open an Engine.IO polling session.
2. Open Socket.IO namespace `1.0.0`.
3. Perform token request and authentication through polling.
4. Upgrade the authenticated session to WebSocket.
5. Keep the WebSocket alive with Engine.IO heartbeats.
6. Send commands and consume runtime messages on the WebSocket.

## Session Open

The initial polling request opens Engine.IO:

```text
GET /socket.io/?EIO=3&transport=polling&token=<token>&t=<timestamp>
```

The DHE returns a payload containing values such as:

```json
{
  "sid": "...",
  "upgrades": ["websocket"],
  "pingInterval": 25000,
  "pingTimeout": 60000
}
```

The integration opens the DHE namespace with:

```text
40/1.0.0
```

## Authentication

Authentication uses Socket.IO events:

| Event | Direction | Purpose |
|---|---|---|
| `token_request` | HA -> DHE | Ask the DHE for a usable token |
| `token_response` | DHE -> HA | Receives and stores the token |
| `authenticate` | HA -> DHE | Authenticates using the returned token |
| `authenticated` | DHE -> HA | Confirms authenticated session |
| `pairing_request` | DHE -> HA | User may need to confirm pairing on the DHE |
| `pairing_result` | DHE -> HA | Pairing result from the DHE |

The token is then reused for later sessions.

## WebSocket Upgrade

After `authenticated`, the integration upgrades to:

```text
ws://<host>:<port>/socket.io/?token=<token>&EIO=3&transport=websocket&sid=<sid>
```

Headers are kept browser-like:

```text
Cookie: io=<sid>
Origin: http://<host>:<port>
Cache-Control: no-cache
Pragma: no-cache
```

The Engine.IO probe sequence is:

```text
HA  -> DHE: 2probe
DHE -> HA : 3probe
HA  -> DHE: 5
```

After this, runtime events are read from the WebSocket.

## Heartbeats

The DHE reports `pingInterval` in the open payload, usually `25000 ms`. The integration sends Engine.IO ping packet `2` at that interval and handles Engine.IO pings from the DHE by replying with `3`.

This matches the browser behavior and avoids the periodic reconnects caused by missing WebSocket heartbeat traffic.

## Runtime Message Format

DHE application messages are Socket.IO event packets in namespace `1.0.0`. Commands use the event name `message` and a payload shaped like:

```json
[
  "message",
  {
    "command": "get:ste.common.odb:value",
    "value": {
      "id": 0,
      "value": ""
    }
  }
]
```

The integration sends numbered Socket.IO message packets for DHE app commands and parses incoming `set:*` and `assign:*` responses into cached Home Assistant entity values.

## Startup Reads

Required startup reads seed the interactive entities:

| ODB ID | Meaning |
|---:|---|
| `0` | Target temperature |
| `1` | Bath fill active |
| `2` | Wellness shower program |
| `3` | Bath fill target volume |
| `4` | Child safety active |
| `5` | Child safety temperature limit |
| `6` | Eco mode |
| `7` | Eco flow limit |
| `10` | Wellness active state |
| `13` | Inlet temperature |
| `14` | Outlet temperature |
| `15` | Water flow |
| `16` | Current power fraction |
| `18` | Operating duration |
| `20` | Nominal power |
| `22` | Scald protection active |
| `24` | Scald protection temperature limit |
| `29` | ODB heating energy |
| `30` | ODB hot water volume |
| `31` | Current bath fill volume |
| `33` | Water heating enabled state, used by the climate entity |
| `34` | Device status; raw `2` indicates water is running, raw `3` is exposed through the error status sensor |
| `61` | Electricity price euros |
| `62` | Water price euros |
| `63` | Possible energy saving |
| `64` | Actual water saving |
| `67` | Raw ODB protocol marker |
| `69` | CO2 emission |
| `70` | Electricity price cents |
| `71` | Water price cents |

Best-effort startup reads collect additional values:

| Command | Purpose |
|---|---|
| `get:ste.common.temperature:memory` | Temperature memory slots |
| `get:ste.app.brushTimer:*` | Brush timer activation, duration and remaining time; the DHE browser UI counts remaining time down locally between device events and resets remaining time to duration on reset/expiry |
| `get:ste.app.showerTimer:*` | Shower timer activation, duration and remaining time; the DHE browser UI counts remaining time down locally between device events and resets remaining time to duration on reset/expiry |
| `get:ste.app.radio:station` | Current radio station metadata |
| `get:ste.app.radio:volume` | Radio volume in percent |
| `get:ste.app.radio:play` | Radio playback state |
| `get:ste.app.radio:paired` | Radio pairing state |
| `get:ste.app.radio:title` | Current radio title |
| `get:ste.app.radio:favorites` | Radio favorite stations |
| `get:ste.app.weather:location` | Weather location and daily forecast payload; with a `LocationId` value it selects that favorite/location |
| `get:ste.app.weather:favorites` | Weather favorite locations |
| `get:ste.app.weather:country` | Selected weather country ID |
| `get:ste.app.consumption:waterWeek` | Weekly water chart |
| `get:ste.app.consumption:waterYear` | Year water chart |
| `get:ste.app.consumption:waterYears` | Multi-year water chart |
| `get:ste.app.consumption:energyWeek` | Weekly energy chart |
| `get:ste.app.consumption:energyYear` | Year energy chart |
| `get:ste.app.consumption:energyYears` | Multi-year energy chart |
| `get:ste.app.consumption:lastUsage` | Last usage payload |
| `get:ste.app.savingMonitor:ActivationRate` | Saving monitor activation rate |
| `get:ste.app.savingMonitor:possible` | Saving monitor possible payload |
| `get:ste.app.savingMonitor:real` | Saving monitor real payload |
| `get:ste.app.savingMonitor:consumption` | Saving monitor consumption payload |
| `get:ste.common.version:*` | Device and version information |
| `get:ste.app.wellness:programs` | Wellness program metadata; the DHE returns program names plus flags such as `coldwater`, and some payloads include temperature-course fields such as `hot` and `cold` |

## On-Demand Commands

Option flows and services use additional commands only when requested:

| Command | Purpose |
|---|---|
| `get:ste.app.radio:genre` | Load the DHE radio genre catalog before genre search |
| `get:ste.app.radio:country` | Load the DHE radio country catalog before country search |
| `get:ste.app.radio:city` | Load the DHE radio city catalog before city search |
| `get:ste.app.radio:stations` | Search stations by `{attribute: "text"|"genre"|"country"|"city", value: "..."}`; country and city searches additionally include `text: "<query>"` |
| `assign:ste.app.radio:favorite` | Toggle a station ID in radio favorites |
| `assign:ste.app.radio:station` | Select/play a station by station ID |
| `assign:ste.app.radio:paired` | Observed pairing button action; `false` disconnects/unpairs according to the DHE UI traffic |
| `get:ste.app.weather:countries` | Load the DHE weather country catalog before weather favorite search |
| `get:ste.app.weather:forecast` | Search weather locations by `{name, countryId}` |
| `assign:ste.app.weather:favorite` | Toggle a location in weather favorites |
| `assign:ste.common.version:controlunitName` | Set the DHE device/control-unit name; the browser UI limits this text field to 30 characters |

The DHE web interface uses `ste.app.wellness:programs` for the wellness program
list. Observed firmware returns the four program IDs, localized names and a
`coldwater` flag. The web view computes the visible program temperature course
from that catalog plus the current target-temperature bounds: `coldwater=true`
shows a cold-water phase where the device disables heating, while
`coldwater=false` displays a reduced cold temperature, usually about `10 C`
below the hot phase unless explicit `cold`/`hot` fields are present.

Temperature memory changes use `assign:ste.common.temperature:memory`. Existing memory slots include the zero-based `id`; adding the next free slot omits `id` and lets the DHE assign it:

```json
{"command": "assign:ste.common.temperature:memory", "value": {"name": "%1 3", "temperature": 40, "operation": "add_change"}}
```

Deleting a memory slot uses the zero-based `id` and `operation: delete`:

```json
{"command": "assign:ste.common.temperature:memory", "value": {"id": 2, "operation": "delete"}}
```

Radio playback uses `assign:ste.app.radio:*`:

```json
{"command": "assign:ste.app.radio:play", "value": true}
```

## Intentionally Ignored App Commands

The web interface exposes a few app commands that are intentionally not mapped
to Home Assistant entities:

| Command | Reason |
|---|---|
| `get/set:ste.app.wellness:progress` | Browser/UI progress helper. Live device tests showed the HA-relevant wellness runtime comes from ODB ID `32` instead. |
| Vendor web assets | The repository never vendors proprietary JS, HTML, CSS or images. Release checks guard against accidentally adding vendor assets. |

## ODB Handling

Mapped ODB values are converted before publishing to Home Assistant:

| ODB ID | Conversion |
|---:|---|
| `0` | Raw tenths to Celsius |
| `4` | Raw truthy value to the `Child safety` switch |
| `5` | Raw tenths to Celsius when value is `200` to `600` |
| `7` | Raw tenths to `L/min` when value is `40` to `150` |
| `13` and `14` | Raw tenths to Celsius |
| `15` | Raw value divided by `10` |
| `16` | Raw percent divided by `100`, multiplied by nominal power |
| `18` | Raw hours as operating duration |
| `20` | Accepts `12` to `36`, `120` to `360`, or `1200` to `3600` formats |
| `29` | Raw `kWh` ODB heating energy |
| `30` | Raw value divided by `10` as `m3` ODB hot water volume |
| `31` | Raw whole liters as current bath fill volume |
| `32` | Wellness runtime value (`ODB_Wellness_Zeit_Norm`) exposed as disabled diagnostic duration sensor `wellness_runtime_normalized` in seconds; observed as second-by-second runtime counter while running and reset to `0` after stop |
| `33` | Inverted heating-disabled flag: raw `0` means water heating enabled, raw `1` means off |
| `34` | Device status enum; raw `1` = normal, raw `2` = water running, raw `3` = service required, raw `4` observed as a water-running transition |
| `61` and `70` | Combined to the electricity price options value as euros plus cents; euros `0` to `32767`, cents `0` to `99` |
| `62` and `71` | Combined to the water price options value as euros plus cents; euros `0` to `32767`, cents `0` to `99` |
| `63` | Raw `kWh` ODB possible energy saving |
| `64` | Raw value divided by `10` as `m3` ODB actual water saving |
| `67` | Raw ODB protocol marker; observed value `1` is not the DHE web interface version |
| `69` | CO2 emission decoded as `raw / 1000` kg/kWh, raw range `0` to `32767` |

The user-facing protocol-version diagnostic comes from the DHE web interface
root page, for example the `manifest-<version>.appcache` or
`assets/ste-dhe-<version>.js` reference. This matches the browser UI
`Versionsinfo` value. ODB ID `67` is kept only as the raw ODB protocol marker
because observed devices report `1` there while the web interface reports the
real browser/app version.

ODB readback responses may arrive as `get:ste.common.odb:value`,
`set:ste.common.odb:value` or `assign:ste.common.odb:value` messages. `get`
readbacks and non-placeholder-sensitive `set`/`assign` readbacks are treated as
fresh device state and are forwarded to measurement entities even when the value
matches the client cache. For the zero-placeholder-sensitive IDs below,
spontaneous `set`/`assign` updates remain runtime updates so real zero totals are
not dropped while a startup read is pending.

Some observed runtime packets encode the ODB debug name in the command suffix
or in a payload field instead of sending a numeric `id`, for example
`set:ste.common.odb:ODB_Is_VS` or
`{"name": "ODB_Is_VS", "value": 27}`. The runtime parser normalizes these
through the `ODB_DEBUG_NAMES` reverse map before dispatch. Empty ID placeholders
are ignored, but conflicting non-empty hints such as `id` and `name` resolving to
different ODB IDs are treated as invalid ODB payloads and are not published.

If a DHE ODB readback is marked with `isValid: false`, it is not published as a normal entity state. Unknown ODB values are logged at debug level for protocol discovery, including the numeric ID, the known Webfrontend ODB name when available, the raw value and the `isValid` flag. Known protocol-only values such as ODB ID `68` are recognized so they do not pollute debug logs.

For ODB IDs `29`, `30`, `63` and `64`, a numeric `0` returned as the immediate readback for a `get:ste.common.odb:value` request is also ignored. These diagnostic totals/savings can report `0` when queried at startup even though the DHE has not emitted a fresh operational value yet. A spontaneous DHE runtime update with value `0` is accepted.

ODB ID `66` is command-only and is not read at startup.

The DHE web interface names the relevant diagnostic ODB entries as `ODB_Heizen_Energie` (WebSocket ID `29`), `ODB_WW_Volumen` (ID `30`), `ODB_St_Geraet_Ba` (ID `34`), `ODB_Gsprt_Energie` (ID `63`) and `ODB_Gsprt_KW_Volumen` (ID `64`). The same web app labels `ste.app.savingMonitor:possible` as potential saving and `ste.app.savingMonitor:real` as actual saving. Live values show ODB ID `63` tracking saving-monitor possible energy and ODB ID `64` tracking saving-monitor real water saving. ODB ID `30` stays labelled as hot-water volume because its web-interface source is `ODB_WW_Volumen`; it can be close to saving-monitor water values but is not the same payload. These ODB values are distinct from the app-level consumption and saving-monitor commands even when current values look similar.

## Recorder Write Throttling

To keep Home Assistant recorder growth under control, the integration throttles high-churn telemetry:

- Climate does not expose inlet/outlet telemetry as recorder-visible attributes;
  those values use dedicated temperature sensors. Climate writes only when its
  control state changes, including setpoint, HVAC mode, availability, dynamic
  max temperature or the `setpoint_below_inlet_temperature` transition.
- Current water flow and current power write every visible runtime change of at least `0.2` in their native units, and they always write transitions between idle `0` and a non-zero value. This keeps live dashboards responsive without writing every tiny device jitter value.
- Timer remaining values and bath-fill volumes are intentionally not write-filtered because they are user-facing live values.
- Saving-monitor sensors update only for the category received from the DHE command (`consumption`, `possible`, `real` or `ActivationRate`) instead of refreshing every saving-monitor sensor on every message.
- Saving-monitor sensor entities additionally use per-entity delta/time write filters to suppress jitter writes.

Repeated raw payloads from weather, radio catalog/search, consumption chart and saving-monitor detail messages are kept in memory only when they are needed for commands, options flows or entity attributes. They are not written repeatedly as normal Home Assistant state changes. Attribute-only updates still write when the recorder-visible value actually changes, for example a selected radio source, weather favorite or climate `target_below_inlet` transition.

Known-but-unexposed ODB values are deliberately recognized and ignored at normal log levels. This keeps protocol discovery useful without filling Home Assistant logs or recorder history with stable internal device values.
