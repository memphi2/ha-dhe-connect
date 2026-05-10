# Stiebel DHE Connect for Home Assistant

Local Home Assistant integration for STIEBEL ELTRON DHE Connect instantaneous water heaters.

The integration talks directly to the DHE web interface on your local network. It uses the same Socket.IO / Engine.IO v3 protocol shape as the browser UI: polling for session setup and authentication, then a WebSocket upgrade for the persistent runtime connection. No cloud service is used.

## Status

- Current version: `1.0.2`
- Home Assistant setup: UI config flow
- HACS type: custom integration
- IoT class: local push
- Network target: local DHE web interface, usually port `8443`
- Scope: one configured DHE Connect device per Home Assistant instance

This is a custom integration and should be used on a trusted local network.

## Highlights

- Local Socket.IO / Engine.IO v3 session with required WebSocket upgrade.
- Browser-style Engine.IO heartbeat handling to keep the DHE session alive.
- Automatic reconnect and diagnostic reconnect counter.
- Target temperature control through the DHE ODB command interface.
- Temperature memory buttons that use the temperatures currently stored in up to 12 memory slots.
- Water and energy consumption sensors, with long-term values disabled by default to keep the device card tidy.
- Last usage, saving monitor, brush timer, shower timer and device diagnostic sensors.
- Eco mode, Eco flow limit, bath fill, currency, maximum temperature and wellness controls.
- Compact radio media player for station metadata, playback and volume.
- Weather entity for the DHE forecast payload.
- Brush timer and shower timer controls.
- Diagnostic online status, reconnect count and device information.

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

On first connection the DHE may request pairing. Confirm the request on the DHE if prompted.

## Pairing token

After successful pairing the local token is stored at:

```text
/config/.storage/stiebel_dhe_connect_token.txt
```

Delete this file and reload the integration if you want to force a new pairing.

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

| Entity | Type | Device class | Source |
|---|---|---|---|
| Online | Binary sensor | `connectivity` | Authenticated persistent session state |

### Media player

| Entity | Features | Source / command | Behavior |
|---|---|---|---|
| Radio | play/pause, volume | `get:ste.app.radio:station`, `volume`, `play`, `paired`, `title`; `assign:ste.app.radio:play`, `volume` | Shows the current radio station/title and controls playback/volume |

The radio entity intentionally does not request the full station catalog. Catalog, favorites and search payloads are treated as known protocol messages when the DHE sends them, but they are not exposed as controls.

### Weather

| Entity | Features | Source / command | Behavior |
|---|---|---|---|
| Weather | daily forecast | `get:ste.app.weather:location` | Shows the DHE weather location, current forecast condition and daily forecast values |

The weather entity exposes the DHE forecast location, daily temperatures, precipitation probabilities and original `icon_id_*` values. Home Assistant weather conditions are derived conservatively from precipitation until the DHE icon ID mapping has been verified with real device data.

### Sensors

| Entity | Unit | Class / category | State class | Source / scaling |
|---|---:|---|---|---|
| Current water flow | `L/min` | `volume_flow_rate` | `measurement` | ODB ID `15 / 10` |
| Current power consumption | `kW` | `power` | `measurement` | ODB ID `16 / 100 * configured_power_kw` |
| Configured power | `kW` | `power`, disabled by default | none | ODB ID `20` |
| Unknown ODB value 22 | none | diagnostic, disabled by default | `measurement` | ODB ID `22`, raw numeric value |
| Inlet temperature | `C` | `temperature`, diagnostic | `measurement` | ODB ID `13 / 10` |
| Outlet temperature | `C` | `temperature`, diagnostic | `measurement` | ODB ID `14 / 10` |
| Unknown temperature 24 | `C` | `temperature`, diagnostic, disabled by default | `measurement` | ODB ID `24 / 10` |
| Unknown ODB value 33 | none | diagnostic, disabled by default | `measurement` | ODB ID `33`, raw numeric value |
| Unknown ODB value 34 | none | diagnostic, disabled by default | `measurement` | ODB ID `34`, raw numeric value |
| Water consumption week | `L` | `water`, disabled by default | `total_increasing` | `set:ste.app.consumption:waterWeek` |
| Water consumption year | `m3` | `water`, disabled by default | `total_increasing` | `set:ste.app.consumption:waterYear` |
| Water consumption years | `m3` | `water`, disabled by default | `total_increasing` | `set:ste.app.consumption:waterYears` |
| Energy consumption week | `kWh` | `energy`, disabled by default | `total` | `set:ste.app.consumption:energyWeek` |
| Energy consumption year | `kWh` | `energy`, disabled by default | `total` | `set:ste.app.consumption:energyYear` |
| Energy consumption years | `kWh` | `energy`, disabled by default | `total` | `set:ste.app.consumption:energyYears` |
| Last usage water | `L` | none | `measurement` | `set:ste.app.consumption:lastUsage.water` |
| Last usage energy | `kWh` | none | `measurement` | `set:ste.app.consumption:lastUsage.energy` |
| Last usage duration | `min` | `duration` | `measurement` | `set:ste.app.consumption:lastUsage.time` |
| Last usage cost | `EUR` | `monetary` | none | `set:ste.app.consumption:lastUsage.costs` |
| Bath fill remaining | `L` | none | `measurement` | Derived from target volume ODB ID `3` minus current bath fill ODB ID `31` |
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
| Brush timer remaining | `M:SS` | none | none | `set:ste.app.brushTimer:remainingMilliseconds` |
| Shower timer remaining | `M:SS` | none | none | `set:ste.app.showerTimer:remainingMilliseconds` |
| Reconnects | count | none | `total_increasing` | Successful reconnect count after the initial connection |
| Device info | text | diagnostic | none | DHE version and device information commands |
| Product ID | text | diagnostic | none | `set:ste.common.version:gadgetData.id` |
| WLAN MAC | text | diagnostic | none | `set:ste.common.version:gadgetData.wlan` |
| Bluetooth MAC | text | diagnostic | none | `set:ste.common.version:gadgetData.bluetooth` |

Consumption sensors expose the DHE chart array as a `chart` attribute and the reported cost as `cost_eur` where available. Saving monitor sensors expose the latest `possible`, `real`, `consumption` and `activation_rate` payloads as attributes.

### Numbers

| Entity | Unit | Range | Mode | Source / command |
|---|---:|---:|---|---|
| Bath fill target volume | `L` | `1` to `300` | slider | ODB ID `3` |
| Maximum temperature | `C` | `30` to `50` | slider | ODB ID `5`, accepts raw tenths or degrees |
| Eco flow limit | `L/min` | `6` to `8` | slider | ODB ID `7`, sent as raw tenths |
| Electricity price | `EUR/kWh` | `0.00` to `9.99` | box | ODB ID `61` for euros and ODB ID `70` for cents |
| Water price | `EUR/m3` | `0.00` to `9.99` | box | ODB ID `62` for euros and ODB ID `71` for cents |
| CO2 emission | `kg/kWh` | `0.00` to `99.99` | box | ODB ID `69`, encoded as `kg/kWh * 1000` |
| Brush timer duration | `min` | `1` to `20` | box | `assign:ste.app.brushTimer:durationMilliseconds` |
| Shower timer duration | `min` | `1` to `20` | box | `assign:ste.app.showerTimer:durationMilliseconds` |
| Temperature memory 1-12 temperature | `C` | `20` to `60` | box | `assign:ste.common.temperature:memory`, memory ID `0` to `11`; created only for slots reported by the DHE |

Temperature memory writes keep the existing memory name and send `operation: add_change`. The Home Assistant entities are only shown for memory slots currently reported by the DHE, so empty memory slots do not clutter the device configuration card.

### Selects

| Entity | Options | Source / command | Behavior |
|---|---|---|---|
| Currency | `EUR`, `GBP`, `CZK`, `PLN`, `CNY`, `USD`, `AUD`, `HKD` | `get:ste.common.currency:value` with a value | Sends the lower-case currency code, matching the DHE app behavior |

The DHE answers the startup currency read with an empty value. The currency select therefore restores the last selected Home Assistant state on startup, falls back to `EUR` on first setup and updates when a currency write or non-empty device response is seen.

### Texts

| Entity | Source / command | Behavior |
|---|---|---|
| Temperature memory 1-12 name | `assign:ste.common.temperature:memory`, memory ID `0` to `11` | Renames a memory slot reported by the DHE |

Temperature memory name writes use the current cached or freshly read memory temperature and send `operation: add_change`. Name fields are created only for memory slots currently reported by the DHE.

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
| Reset brush timer | `assign:ste.app.brushTimer:reset` | Resets brush timer remaining time and activation state |
| Reset shower timer | `assign:ste.app.showerTimer:reset` | Resets shower timer remaining time and activation state |
| Temperature memory 1-12 | ODB ID `66` command | Sends the temperature stored in the matching memory slot; created only for slots reported by the DHE |
| Delete temperature memory 3-12 | `assign:ste.common.temperature:memory` | Deletes the matching memory slot with `operation: delete`; memory slots 1 and 2 are fixed presets and are not deletable |

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
| `22` | Unknown raw diagnostic value, disabled entity |
| `24` | Unknown temperature, disabled entity |
| `31` | Current bath fill volume |
| `33` | Unknown raw diagnostic value, disabled entity |
| `34` | Unknown raw diagnostic value, disabled entity |
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
| `get:ste.app.weather:location` | Weather location and daily forecast payload |
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
| `5` | Raw tenths to Celsius when value is `300` to `500` |
| `7` | Raw tenths to `L/min` when value is `60` to `80` |
| `13` and `14` | Raw tenths to Celsius |
| `15` | Raw value divided by `10` |
| `16` | Raw percent divided by `100`, multiplied by configured power |
| `20` | Accepts `18` to `24`, `180` to `240`, or `1800` to `2400` formats |
| `61` and `70` | Combined to the `Electricity price` number as euros plus cents |
| `62` and `71` | Combined to the `Water price` number as euros plus cents |
| `69` | CO2 emission decoded as `raw / 1000` kg/kWh |

If a DHE ODB readback is marked with `isValid: false`, it is not published as a normal entity state. Unknown ODB values are logged at debug level for protocol discovery.

ODB ID `66` is command-only and is not read at startup.

## Availability and reconnect behavior

The client runs a single persistent session loop. Home Assistant entities subscribe to cached setpoint, measurement, online, availability and reconnect callbacks. When an entity is added after a value was already received, the current cached value is delivered immediately.

Short reconnects do not immediately drop every entity to unavailable. Entities with a known valid value stay available during brief reconnect phases where this is safe, while the diagnostic `Online` entity and reconnect counter show the real connection state.


## Security notes

- Use only on a trusted local network.
- Do not expose the DHE web interface or port `8443` to the internet.
- The pairing token is stored under Home Assistant's configuration directory.
- Tokens are not intentionally written to normal logs.

## Troubleshooting

| Symptom | Check |
|---|---|
| Integration cannot connect | Verify host, port and browser access to `http://<host>:<port>/` |
| Pairing repeats | Delete `/config/.storage/stiebel_dhe_connect_token.txt` and pair again |
| Entities stay unavailable | Check the `Online` binary sensor and Home Assistant logs for DHE session errors |
| Reconnect counter increases often | Confirm the WebSocket connection is not blocked and no second client is fighting for the DHE session |
| Radio entity has no station/title | Open or change the radio once on the DHE UI so the device publishes station metadata |
| Water entity missing from dashboard | Wait for Home Assistant statistics discovery, which can take up to two hours |
| Temperature write fails | Check DHE limits, locks, device mode and local reachability |
| Timer reset does not update | Confirm that the DHE accepts the matching brush/shower timer reset command |

## Disclaimer

This is an unofficial custom integration. It is not affiliated with, endorsed by, sponsored by or approved by STIEBEL ELTRON. Product names are used only to describe compatibility with the local DHE Connect web interface. STIEBEL ELTRON trademarks and logos are not included or licensed by this project.
