# Stiebel DHE Connect for Home Assistant

Local Home Assistant integration for STIEBEL ELTRON DHE Connect instantaneous water heaters.

The integration talks directly to the DHE web interface on your local network. It uses the same Socket.IO / Engine.IO v3 protocol shape as the browser UI: polling for session setup and authentication, then a WebSocket upgrade for the persistent runtime connection. No cloud service is used.

## Status

- Current version: `1.0.7-beta`
- Home Assistant setup: UI config flow
- HACS type: custom integration
- IoT class: local push
- Network target: local DHE web interface, usually port `8443`
- Scope: multiple configured DHE Connect devices per Home Assistant instance

This is a custom integration and should be used on a trusted local network.

Development and protocol mapping for this release were assisted by OpenAI Codex.

## Highlights

- Local Socket.IO / Engine.IO v3 session with required WebSocket upgrade.
- Browser-style Engine.IO heartbeat handling to keep the DHE session alive.
- Automatic reconnect and diagnostic reconnect counter.
- Target temperature control through the DHE ODB command interface.
- Temperature memory controls for all 12 supported slots; slots 3 to 12 are disabled by default.
- Total water and energy consumption sensors are enabled by default; detailed live, last usage, timer and saving-monitor sensors start disabled to keep the device card tidy.
- Eco mode, Eco flow limit, bath fill, maximum temperature and wellness controls; currency, cost and CO2 settings live in the integration options.
- Compact radio media player for station metadata, playback, volume and favorites.
- Options-flow radio search by full text, DHE genre catalog, country catalog or city catalog.
- Weather entity for the DHE forecast payload.
- Brush timer and shower timer controls.
- General diagnostic status, reconnect count, connection details and device information.

## Installation

### HACS custom repository

1. Open HACS.
2. Go to `Integrations`.
3. Open the three-dot menu and choose `Custom repositories`.
4. Add this repository URL:

   ```text
   https://github.com/memphi2/ha-dhe-connect
   ```

5. Select category `Integration`.
6. Install `Stiebel DHE Connect`.
7. Restart Home Assistant.
8. Add the integration from `Settings` -> `Devices & services`.

### Manual installation

Copy the integration directory to:

```text
/config/custom_components/stiebel_dhe_connect/
```

After copying, restart Home Assistant and add `Stiebel DHE Connect` from the UI.

## Configuration

The config flow asks for:

| Field | Example | Notes |
|---|---|---|
| Host | `192.168.1.100` | IP address or hostname only |
| Port | `8443` | DHE web interface port |
| Device name | `DHE Connect` | Name shown in Home Assistant |

The host field intentionally rejects URLs with paths, usernames, query strings or embedded ports. The port must be between `1` and `65535`.

On first connection Home Assistant validates the DHE pairing before the integration entry is created.

### Multiple devices

Add one config entry per DHE device:

1. `Settings` -> `Devices & services` -> `Add integration` -> `Stiebel DHE Connect`
2. Enter host, port and name for that exact DHE
3. Complete pairing on the device display (required)
4. Repeat for the next DHE

Each config entry keeps its own runtime session, token file and entity set.

### First pairing flow

1. Add `Stiebel DHE Connect` from `Settings` -> `Devices & services`.
2. Enter only the DHE host/IP, port and a provisional device name.
3. Submit the form, then click `OK` on the pairing confirmation step.
4. Confirm the pairing request on the DHE device display and complete the confirmation there (required).
5. Home Assistant creates the integration entry only after pairing and login have completed.
6. Assign the device to an area and adjust entity names as desired.

## Pairing token

After successful pairing the local token is stored per configured DHE target at:

```text
/config/.storage/stiebel_dhe_connect_token_<host>_<port>.txt
```

With multiple DHE devices, each host/port pair gets its own token file.
On upgrade from older single-device versions, the legacy global token file is moved once to the new per-target file and then consumed.
For very long hostnames, the token filename uses a bounded host component with a hash suffix to avoid filesystem filename-length errors.

Use the disabled-by-default `Repair pairing` button if you want to force a new pairing from Home Assistant.
The button deletes the stored token, reconnects and shows a pairing notification while the DHE waits for confirmation.
If pairing fails repeatedly, the integration pauses automatic retries after three attempts; use `Repair pairing` again after checking the DHE.
Manual token deletion is only needed if Home Assistant cannot load the integration far enough to expose the button.

The integration attempts to store the token file with `0600` permissions where the Home Assistant filesystem supports it.

## Entities

Home Assistant entity names are translated through `translations/en.json` and `translations/de.json`. The tables below use the English names and list the underlying DHE source for maintainers.

### Climate

| Entity | Type | Source | Behavior |
|---|---|---|---|
| DHE Connect | Climate | ODB ID `0`, command ODB ID `66` | Reads target temperature and writes new setpoints in `0.5 C` steps |

The climate entity keeps the last valid target temperature during short reconnect phases and exposes diagnostic attributes:

| Attribute | Meaning |
|---|---|
| `communication_model` | `persistent_socketio_websocket` |
| `connection_state` | `starting`, `connected`, `reconnecting` or `unavailable` |
| `readback_id` | ODB ID used for target temperature readback |
| `write_id` | ODB ID used for setpoint commands |

### Binary sensors

No dedicated binary sensors are created by default in the current entity model.

### Media player

| Entity | Features | Source / command | Behavior |
|---|---|---|---|
| Radio | play/pause, volume, source selection, previous/next favorite | `get:ste.app.radio:station`, `volume`, `play`, `paired`, `title`, `favorites`; `assign:ste.app.radio:play`, `volume`, `station` | Shows the current radio title, station short description or station name, controls playback/volume and switches between radio favorites |

The radio entity intentionally does not request the full station catalog during startup. It does read the small favorites list so Home Assistant can expose radio favorites as media-player sources and use previous/next to cycle through them. The options flow can search stations by full text, DHE genre catalog, or by DHE country/city catalog plus a search term, then add the selected station as a DHE radio favorite and activate it. Genre searches send the selected genre directly; full-text search sends `{attribute: "text", value: "<query>"}`; country and city searches send the selected catalog value and include the entered search term as additional text. Existing radio favorites can also be removed from the options flow. Catalog, favorites and search payloads are treated as known protocol messages so they do not pollute debug logs.

### Weather

| Entity | Features | Source / command | Behavior |
|---|---|---|---|
| Weather | daily forecast | `get:ste.app.weather:location` | Shows the DHE weather location, current forecast condition and daily forecast values |

The weather entity exposes the DHE forecast location, including `city`, `country` and a combined `location` attribute in `place, country` format, daily temperatures, precipitation probabilities and original `icon_id_*` values. The observed DHE weather icons are mapped to Home Assistant weather conditions where verified from device traffic: `1`/`2` = sunny, `3`/`4`/`6` = partly cloudy, `5` = cloudy and `7`/`8` = rainy. Unknown icon IDs remain visible as attributes and fall back to precipitation-based conditions. Weather favorites, forecast search results and the selected country are treated as known protocol messages; the full country catalog is recognized but not requested during startup because it is very large.

Weather location search uses the same split city/country workflow as the DHE UI. The integration options can add and remove weather favorites. The `Weather location` select is enabled by default and switches between existing favorites from Home Assistant. The service `stiebel_dhe_connect.search_weather_location` sends `get:ste.app.weather:forecast` with `name` and `country_id`; the returned results are exposed as `forecast_results` attributes. The service `stiebel_dhe_connect.toggle_weather_favorite` can toggle an existing result by `result_number` or run a fresh search first when `name` and `country_id` are provided. The DHE uses the same `assign:ste.app.weather:favorite` command to add and remove favorites.

Selecting the active weather location is a separate step. The service `stiebel_dhe_connect.select_weather_location` sends `get:ste.app.weather:location` with the selected `LocationId`, matching the browser protocol used when switching to a favorite. It can select by exact `location_id`, by the current search `result_number`, or run a fresh name/country search first. When multiple DHE devices are configured, include `entry_id` in service data to target one integration entry. Example for toggling New York in the USA:

```yaml
service: stiebel_dhe_connect.toggle_weather_favorite
data:
  entry_id: 01HXXXXXXXXXXXXXXX
  name: New York
  country_id: 143
  result_number: 1
```

Example for switching to an existing favorite by `LocationId`:

```yaml
service: stiebel_dhe_connect.select_weather_location
data:
  entry_id: 01HXXXXXXXXXXXXXXX
  location_id: ID=320@ID2=84666@REGIO=5@COUNTRY_ID=34
```

### Sensors

| Entity | Unit | Class / category | State class | Source / scaling |
|---|---:|---|---|---|
| Current water flow | `L/min` | `volume_flow_rate`, disabled by default | `measurement` | ODB ID `15 / 10` |
| Current power consumption | `kW` | `power`, disabled by default | `measurement` | ODB ID `16 / 100 * configured_power_kw` |
| Configured power | `kW` | `power`, disabled by default | none | ODB ID `20` |
| Inlet temperature | `C` | `temperature`, diagnostic, disabled by default | `measurement` | ODB ID `13 / 10` |
| Outlet temperature | `C` | `temperature`, diagnostic, disabled by default | `measurement` | ODB ID `14 / 10` |
| Water consumption week | `L` | `water`, disabled by default | `total_increasing` | `set:ste.app.consumption:waterWeek` |
| Water consumption year | `m3` | `water`, disabled by default | `total_increasing` | `set:ste.app.consumption:waterYear` |
| Water consumption years | `m3` | `water` | `total_increasing` | `set:ste.app.consumption:waterYears` |
| Energy consumption week | `kWh` | `energy`, disabled by default | `total` | `set:ste.app.consumption:energyWeek` |
| Energy consumption year | `kWh` | `energy`, disabled by default | `total` | `set:ste.app.consumption:energyYear` |
| Energy consumption years | `kWh` | `energy` | `total` | `set:ste.app.consumption:energyYears` |
| Last usage water | `L` | disabled by default | `measurement` | `set:ste.app.consumption:lastUsage.water` |
| Last usage energy | `kWh` | disabled by default | `measurement` | `set:ste.app.consumption:lastUsage.energy` |
| Last usage duration | `M:SS` | disabled by default | none | `set:ste.app.consumption:lastUsage.time`, rendered like timer remaining values |
| Last usage cost | `EUR` | `monetary`, disabled by default | none | `set:ste.app.consumption:lastUsage.costs` |
| Bath fill remaining | `L` | disabled by default | `measurement` | Derived from target volume ODB ID `3` minus current bath fill ODB ID `31` |
| Saving monitor consumption water | `L` | disabled by default | `measurement` | `set:ste.app.savingMonitor:consumption.water_l`, rounded to 2 decimals |
| Saving monitor consumption energy | `kWh` | disabled by default | `measurement` | `set:ste.app.savingMonitor:consumption.energy_Wh / 1000`, rounded to 2 decimals |
| Saving monitor consumption CO2 | `kg` | disabled by default | `measurement` | `set:ste.app.savingMonitor:consumption.emission_Co2Kg`, rounded to 2 decimals |
| Saving monitor activation rate | `%` | disabled by default | `measurement` | `set:ste.app.savingMonitor:ActivationRate`, rounded to 1 decimal |
| Saving monitor possible water saving | `L` | disabled by default | `measurement` | `set:ste.app.savingMonitor:possible.water_l`, rounded to 2 decimals |
| Saving monitor possible energy saving | `kWh` | disabled by default | `measurement` | `set:ste.app.savingMonitor:possible.energy_Wh / 1000`, rounded to 2 decimals |
| Saving monitor possible CO2 saving | `kg` | disabled by default | `measurement` | `set:ste.app.savingMonitor:possible.emission_Co2Kg`, rounded to 2 decimals |
| Saving monitor possible cost saving | `EUR` | `monetary`, disabled by default | none | `set:ste.app.savingMonitor:possible.value_E`, rounded to 2 decimals |
| Saving monitor real water saving | `L` | disabled by default | `measurement` | `set:ste.app.savingMonitor:real.water_l`, rounded to 2 decimals |
| Saving monitor real energy saving | `kWh` | disabled by default | `measurement` | `set:ste.app.savingMonitor:real.energy_Wh / 1000`, rounded to 2 decimals |
| Saving monitor real CO2 saving | `kg` | disabled by default | `measurement` | `set:ste.app.savingMonitor:real.emission_Co2Kg`, rounded to 2 decimals |
| Saving monitor real cost saving | `EUR` | `monetary`, disabled by default | none | `set:ste.app.savingMonitor:real.value_E`, rounded to 2 decimals |
| Brush timer remaining | `M:SS` | disabled by default | none | `set:ste.app.brushTimer:remainingMilliseconds` |
| Shower timer remaining | `M:SS` | disabled by default | none | `set:ste.app.showerTimer:remainingMilliseconds` |
| Reconnects | count | diagnostic | `total_increasing` | Successful reconnect count after the initial connection |
| Connection state | text | diagnostic | none | Client session state such as `starting`, `connected`, `reconnecting` or `stopped` |
| Last reconnect reason | text | diagnostic | none | Last recorded session failure or forced reconnect reason |
| Temperature error status | text | diagnostic | none | General error status, including target temperature below inlet temperature |
| Device info | text | diagnostic, disabled by default | none | DHE version and device information commands |
| Product ID | text | diagnostic, disabled by default | none | `set:ste.common.version:gadgetData.id` |
| WLAN MAC | text | diagnostic, disabled by default | none | `set:ste.common.version:gadgetData.wlan` |
| Bluetooth MAC | text | diagnostic, disabled by default | none | `set:ste.common.version:gadgetData.bluetooth` |

Consumption sensors expose the DHE chart array as a `chart` attribute and the reported cost as `cost_eur` where available. Saving monitor sensors expose the latest `possible`, `real`, `consumption` and `activation_rate` payloads as attributes.

### Numbers

| Entity | Unit | Range | Mode | Source / command |
|---|---:|---:|---|---|
| Bath fill target volume | `L` | `1` to `300` | slider | ODB ID `3` |
| Maximum temperature | `C` | `20` to `50` | slider | ODB ID `5`, accepts raw tenths or degrees |
| Eco flow limit | `L/min` | `6` to `8` | slider | ODB ID `7`, sent as raw tenths |
| Brush timer duration | `s` | `60` to `1200`, step `1` | box | `assign:ste.app.brushTimer:durationMilliseconds`; shown in Home Assistant as seconds |
| Shower timer duration | `s` | `60` to `1200`, step `1` | box | `assign:ste.app.showerTimer:durationMilliseconds`; shown in Home Assistant as seconds |
| Temperature memory 1-12 temperature | `C` | `20` to `60` | box | `assign:ste.common.temperature:memory`, memory ID `0` to `11`; slots 3 to 12 disabled by default |

Temperature memory writes keep the existing memory name and send `operation: add_change`. Slots 1 and 2 are enabled by default. Slots 3 to 12 are created in the entity registry but disabled by default, so they can be enabled explicitly without cluttering the device configuration card.

Currency, electricity price, water price and CO2 emission are configured from the integration options under `Costs & emissions` instead of being exposed as entities. The DHE writes use the same protocol values as the browser UI: currency via `get:ste.common.currency:value`, electricity price via ODB IDs `61`/`70`, water price via ODB IDs `62`/`71` and CO2 emission via ODB ID `69`.

### Selects

| Entity | Options | Source / command | Behavior |
|---|---|---|---|
| Weather location | weather favorites | `get:ste.app.weather:location` with a `LocationId` value | Selects the active DHE weather favorite |

### Texts

| Entity | Source / command | Behavior |
|---|---|---|
| Temperature memory 1-12 name | `assign:ste.common.temperature:memory`, memory ID `0` to `11` | Renames a memory slot; slots 3 to 12 disabled by default |

Temperature memory name writes use the current cached or freshly read memory temperature and send `operation: add_change`. Name fields for slots 3 to 12 are disabled by default and can be enabled when those optional memories are used.

### Switches

| Entity | Source / command | Behavior |
|---|---|---|
| Eco mode | ODB ID `6` | Turns Eco mode on or off |
| Bath fill | ODB ID `1` | Starts or stops bath filling |
| Maximum temperature limit | ODB ID `4` | Enables or disables the maximum temperature limit |
| Brush timer | `assign:ste.app.brushTimer:activation` | Starts or stops the brush timer |
| Shower timer | `assign:ste.app.showerTimer:activation` | Starts or stops the shower timer |
| Cold prevention | ODB ID `2` value `1`, trigger ODB ID `10` | Starts wellness cold prevention, off sends stop |
| Winter refresh | ODB ID `2` value `2`, trigger ODB ID `10` | Starts winter refresh, off sends stop |
| Summer fitness | ODB ID `2` value `3`, trigger ODB ID `10` | Starts summer fitness, off sends stop |
| Circulation support | ODB ID `2` value `4`, trigger ODB ID `10` | Starts circulation support, off sends stop |

Wellness programs are triggered by writing the program ID and then sending the DHE trigger value. The integration derives switch state from the latest program and stop/trigger readbacks.

### Buttons

| Entity | Command | Behavior |
|---|---|---|
| Reset brush timer | `assign:ste.app.brushTimer:reset` | Resets brush timer remaining time and activation state; disabled by default |
| Reset shower timer | `assign:ste.app.showerTimer:reset` | Resets shower timer remaining time and activation state; disabled by default |
| Repair pairing | local token reset and reconnect | Deletes the stored DHE token, starts a fresh pairing attempt and asks the user to confirm pairing on the DHE; disabled by default |
| Disconnect radio pairing | `assign:ste.app.radio:paired` with `false` | Sends the observed DHE radio pairing disconnect action |
| Temperature memory 1-12 | ODB ID `66` command | Sends the temperature stored in the matching memory slot; slots 3 to 12 disabled by default |
| Delete temperature memory 3-12 | `assign:ste.common.temperature:memory` | Deletes the matching memory slot with `operation: delete`; disabled by default; memory slots 1 and 2 are fixed presets and are not deletable |

The memory preset buttons do not send fixed temperatures. They read the current memory slot value from the DHE cache, refresh it if needed, build the ODB ID `66` button payload from that temperature and send it.

## Water dashboard support

The three water consumption sensors are exposed as real Home Assistant water meters:

- `device_class=water`
- `state_class=total_increasing`
- units `L` or `m3`

This allows them to be used in the Home Assistant energy/water dashboard after you enable the desired disabled-by-default consumption entities. Home Assistant may need up to two hours before newly added long-term statistics entities appear in dashboard pickers.

## Protocol

### Transport overview

The DHE web UI uses Socket.IO over Engine.IO v3. The integration mirrors that behavior closely:

1. Open an Engine.IO polling session.
2. Open Socket.IO namespace `1.0.0`.
3. Perform token request and authentication through polling.
4. Upgrade the authenticated session to WebSocket.
5. Keep the WebSocket alive with Engine.IO heartbeats.
6. Send commands and consume runtime messages on the WebSocket.

### Session open

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

### Authentication

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

### WebSocket upgrade

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

### Heartbeats

The DHE reports `pingInterval` in the open payload, usually `25000 ms`. The integration sends Engine.IO ping packet `2` at that interval and handles Engine.IO pings from the DHE by replying with `3`.

This matches the browser behavior and avoids the periodic reconnects caused by missing WebSocket heartbeat traffic.

### Runtime message format

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

### Startup reads

Required startup reads seed the interactive entities:

| ODB ID | Meaning |
|---:|---|
| `0` | Target temperature |
| `1` | Bath fill active |
| `2` | Wellness shower program |
| `3` | Bath fill target volume |
| `4` | Maximum temperature limit active |
| `5` | Maximum temperature |
| `6` | Eco mode |
| `7` | Eco flow limit |
| `10` | Program stop/trigger state |
| `13` | Inlet temperature |
| `14` | Outlet temperature |
| `15` | Water flow |
| `16` | Current power fraction |
| `20` | Configured power |
| `22` | Known noisy diagnostic value, not exposed as an entity |
| `24` | Known noisy temperature value, not exposed as an entity |
| `31` | Current bath fill volume |
| `33` | Water heating enabled state, used by the climate entity |
| `34` | Known noisy diagnostic value, not exposed as an entity |
| `61` | Electricity price euros |
| `62` | Water price euros |
| `69` | CO2 emission |
| `70` | Electricity price cents |
| `71` | Water price cents |

Best-effort startup reads collect additional values:

| Command | Purpose |
|---|---|
| `get:ste.common.temperature:memory` | Temperature memory slots |
| `get:ste.app.brushTimer:*` | Brush timer activation, duration and remaining time |
| `get:ste.app.showerTimer:*` | Shower timer activation, duration and remaining time |
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
| `get:ste.app.wellness:programs` | Wellness program metadata |

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

Currency changes use the same command as the DHE app:

```json
{"command": "get:ste.common.currency:value", "value": "eur"}
```

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

### ODB handling

Mapped ODB values are converted before publishing to Home Assistant:

| ODB ID | Conversion |
|---:|---|
| `0` | Raw tenths to Celsius |
| `4` | Raw truthy value to the `Maximum active` switch |
| `5` | Raw tenths to Celsius when value is `200` to `500` |
| `7` | Raw tenths to `L/min` when value is `60` to `80` |
| `13` and `14` | Raw tenths to Celsius |
| `15` | Raw value divided by `10` |
| `16` | Raw percent divided by `100`, multiplied by configured power |
| `20` | Accepts `18` to `24`, `180` to `240`, or `1800` to `2400` formats |
| `61` and `70` | Combined to the electricity price options value as euros plus cents |
| `62` and `71` | Combined to the water price options value as euros plus cents |
| `69` | CO2 emission decoded as `raw / 1000` kg/kWh |

If a DHE ODB readback is marked with `isValid: false`, it is not published as a normal entity state. Unknown ODB values are logged at debug level for protocol discovery.

ODB ID `66` is command-only and is not read at startup.

## Availability and reconnect behavior

The client runs a single persistent session loop. Home Assistant entities subscribe to cached setpoint, measurement, online, availability and reconnect callbacks. When an entity is added after a value was already received, the current cached value is delivered immediately.

Availability is strict live. If the runtime connection drops, entities become unavailable until fresh runtime data is received again.

Diagnostic sensors expose the current client connection state and the last reconnect reason. These are intended for troubleshooting connection stalls, WebSocket churn and device-side session closes.

## Validation

The repository includes a lightweight validation script:

```bash
python scripts/check_integration.py
```

It checks the manifest, HACS metadata, required repository files, translation key parity and Python syntax without writing bytecode artifacts. The same check runs in the `Validate` GitHub Actions workflow.


## Security notes

- Use only on a trusted local network.
- Do not expose the DHE web interface or port `8443` to the internet.
- The pairing token is stored under Home Assistant's configuration directory.
- Tokens are not intentionally written to normal logs.

## Troubleshooting

| Symptom | Check |
|---|---|
| Integration cannot connect | Verify host, port and browser access to `http://<host>:<port>/` |
| Device appears twice after update | Current `1.0.6` keeps legacy host identifiers during upgrade. If a stale duplicate already exists from older test builds, remove only the stale device entry once |
| Service call hits the wrong DHE | In multi-device setups always include `entry_id` in service data |
| Pairing repeats | Enable and use the disabled-by-default `Repair pairing` button first. If needed, delete the matching `/config/.storage/stiebel_dhe_connect_token_<host>_<port>.txt` file and pair again |
| Entities stay unavailable | Check the `Connection state` / `Temperature error status` diagnostic sensors and Home Assistant logs for DHE session errors |
| Reconnect counter increases often | Confirm the WebSocket connection is not blocked and no second client is fighting for the DHE session |
| Radio entity has no station/title | Open or change the radio once on the DHE UI so the device publishes station metadata |
| Water entity missing from dashboard | Wait for Home Assistant statistics discovery, which can take up to two hours |
| Temperature write fails | Check DHE limits, locks, device mode and local reachability |
| Timer reset does not update | Confirm that the DHE accepts the matching brush/shower timer reset command |

## Disclaimer

This is an unofficial custom integration. It is not affiliated with, endorsed by, sponsored by or approved by STIEBEL ELTRON. Product names are used only to describe compatibility with the local DHE Connect web interface. STIEBEL ELTRON trademarks and logos are not included or licensed by this project.
