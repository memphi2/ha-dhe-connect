# Entity Reference

Home Assistant entity names are translated through `translations/en.json` and `translations/de.json`. The tables below use the English names and list the underlying DHE source for maintainers. User-facing entity names avoid protocol markers such as `ODB`; the source column records when a value comes from an ODB ID.

## Climate

| Entity | Type | Source | Behavior |
|---|---|---|---|
| DHE Connect | Climate | ODB ID `0`, command ODB ID `66` | Reads target temperature and writes new setpoints in `0.5 C` steps |

The climate entity keeps the last valid target temperature during short reconnect phases. The dedicated diagnostic sensors expose the live reconnect state and delay without adding those volatile values to normal entity attributes.

Its maximum settable target temperature is capped by the `Internal scald protection (Tmax jumper)` integration option. When child safety is active, the Climate maximum uses the lower value of the `Tmax` jumper and the `Child safety temperature limit` number entity. The default internal scald-protection option is `60`.

| Attribute | Meaning |
|---|---|
| `communication_model` | `persistent_socketio_websocket` |
| `connection_state` | `starting`, `connected` or `unavailable`; the separate `Connection state` diagnostic sensor reports `reconnecting` during reconnect grace |
| `readback_id` | ODB ID used for target temperature readback |
| `write_id` | ODB ID used for setpoint commands |
| `inlet_temperature` | Latest inlet/cold-water temperature from ODB ID `13` |
| `outlet_temperature` | Latest outlet/hot-water temperature from ODB ID `14` |
| `water_heating_enabled` | Decoded heating state from inverted ODB ID `33` |
| `child_safety_active` | Child-safety state from ODB ID `4` |
| `child_safety_temperature_limit` | Effective child-safety limit from ODB ID `5`, capped by the configured internal scald-protection jumper |
| `child_safety_temperature_limit_raw` | Raw child-safety limit read from ODB ID `5` before the local jumper cap |
| `internal_scald_protection` | Locally configured physical jumper position |

## Binary Sensors

| Entity | Class / category | Source / behavior |
|---|---|---|
| Scald protection active | diagnostic, disabled by default | ODB ID `22`, true when the DHE reports the anti-scald protection as active |

## Media Player

| Entity | Features | Source / command | Behavior |
|---|---|---|---|
| Radio | play/pause, volume, source selection, previous/next favorite | `get:ste.app.radio:station`, `volume`, `play`, `paired`, `title`, `favorites`; `assign:ste.app.radio:play`, `volume`, `station` | Shows the current radio title, station short description or station name, controls playback/volume and switches between radio favorites |

The radio entity intentionally does not request the full station catalog during startup. It does read the small favorites list so Home Assistant can expose radio favorites as media-player sources and use previous/next to cycle through them. The options flow can search stations by full text, DHE genre catalog, or by DHE country/city catalog plus a search term, then add the selected station as a DHE radio favorite and activate it. Genre searches send the selected genre directly; full-text search sends `{attribute: "text", value: "<query>"}`; country and city searches send the selected catalog value and include the entered search term as additional text. Existing radio favorites can also be removed from the options flow. Catalog, favorites and search payloads are treated as known protocol messages so they do not pollute debug logs.

## Weather

| Entity | Features | Source / command | Behavior |
|---|---|---|---|
| Weather | daily forecast | `get:ste.app.weather:location` | Shows the DHE weather location, current forecast condition and daily forecast values |

The weather entity exposes the DHE forecast location, including `city`, `country` and a combined `location` attribute in `place, country` format, daily temperatures, precipitation probabilities and original `icon_id_*` values. The observed DHE weather icons are mapped to Home Assistant weather conditions where verified from device traffic: `1`/`2` = sunny, `3`/`4`/`6` = partly cloudy, `5` = cloudy and `7`/`8` = rainy. Unknown icon IDs remain visible as attributes and fall back to precipitation-based conditions. Weather favorites, forecast search results and the selected country are treated as known protocol messages; the full country catalog is recognized but not requested during startup because it is very large.

Weather location search uses the same split city/country workflow as the DHE UI. The integration options can add and remove weather favorites. The `Weather location` select is enabled by default and switches between existing favorites from Home Assistant. `search_weather_location` returns forecast results in `forecast_results` attributes.

Weather favorite service actions:

- `add_weather_favorite`: safe add behavior (no toggle off if already present, requires a fresh favorite list on confirmation)
- `remove_weather_favorite`: safe remove behavior (no toggle on if already missing, requires a fresh favorite list on removal)
- `toggle_weather_favorite`: low-level toggle (protocol-native), can add or remove depending on current state

All services share the same selection input model as before (`entry_id`, `result_number`, `location_id`, `name`, `country_id`) and are backed by `assign:ste.app.weather:favorite`.

Selecting the active weather location is a separate step. The service `stiebel_dhe_connect.select_weather_location` sends `get:ste.app.weather:location` with the selected `LocationId`, matching the browser protocol used when switching to a favorite. It can select by exact `location_id`, by the current search `result_number`, or run a fresh name/country search first. When multiple DHE devices are configured, include `entry_id` in service data to target one integration entry. Example for toggling New York in the USA:

```yaml
service: stiebel_dhe_connect.toggle_weather_favorite
data:
  entry_id: 01HXXXXXXXXXXXXXXX
  name: New York
  country_id: 143
  result_number: 1
```

Example for explicitly adding or removing the same location:

```yaml
service: stiebel_dhe_connect.add_weather_favorite
data:
  entry_id: 01HXXXXXXXXXXXXXXX
  name: New York
  country_id: 143
  result_number: 1
```

```yaml
service: stiebel_dhe_connect.remove_weather_favorite
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

## Sensors

| Entity | Unit | Class / category | State class | Source / scaling |
|---|---:|---|---|---|
| Current water flow | `L/min` | `volume_flow_rate` | `measurement` | ODB ID `15 / 10`, suggested display precision `1` |
| Current power consumption | `kW` | `power` | `measurement` | ODB ID `16 / 100 * nominal_power_kw` |
| Nominal power | `kW` | `power`, disabled by default | none | ODB ID `20` |
| Operating duration | `h` | `duration`, diagnostic, disabled by default | `total_increasing` | ODB ID `18`, raw hours |
| Inlet temperature | `C` | `temperature`, diagnostic, disabled by default | `measurement` | ODB ID `13 / 10` |
| Outlet temperature | `C` | `temperature`, diagnostic, disabled by default | `measurement` | ODB ID `14 / 10` |
| Scald protection temperature limit | `C` | `temperature`, diagnostic, disabled by default | none | ODB ID `24 / 10` |
| Device status | text | `enum`, diagnostic, disabled by default | none | ODB ID `34`; status code `2` means water is running, status code `3` is surfaced through the error status sensor |
| Protocol version | text | diagnostic, disabled by default | none | DHE web interface version from `web:index`; the raw ODB ID `67` marker is kept as diagnostic context only |
| Water consumption week | `L` | `water`, disabled by default | `total_increasing` | `set:ste.app.consumption:waterWeek` |
| Water consumption year | `m3` | `water`, disabled by default | `total_increasing` | `set:ste.app.consumption:waterYear` |
| Total water consumption | `m3` | `water` | `total_increasing` | `set:ste.app.consumption:waterYears` |
| Hot water volume | `m3` | `water`, disabled by default | `total_increasing` | ODB ID `30 / 10` |
| Energy consumption week | `kWh` | `energy`, disabled by default | `total` | `set:ste.app.consumption:energyWeek` |
| Heating energy | `kWh` | `energy`, disabled by default | `total_increasing` | ODB ID `29` |
| Possible energy saving | `kWh` | `energy`, diagnostic, disabled by default | `total` | ODB ID `63` |
| Actual water saving | `m3` | `water`, diagnostic, disabled by default | `total` | ODB ID `64 / 10` |
| Energy consumption year | `kWh` | `energy`, disabled by default | `total` | `set:ste.app.consumption:energyYear` |
| Total energy consumption | `kWh` | `energy` | `total` | `set:ste.app.consumption:energyYears` |
| Last usage water | `L` | disabled by default | `measurement` | `set:ste.app.consumption:lastUsage.water` |
| Last usage energy | `kWh` | disabled by default | `measurement` | `set:ste.app.consumption:lastUsage.energy` |
| Last usage duration | `M:SS` | disabled by default | none | `set:ste.app.consumption:lastUsage.time`, rendered like timer remaining values |
| Last usage cost | `EUR` | `monetary`, disabled by default | none | `set:ste.app.consumption:lastUsage.costs` |
| Bath fill remaining | `L` | disabled by default | `measurement` | Derived as whole liters from target volume ODB ID `3` minus current bath fill ODB ID `31` |
| Current bath fill volume | `L` | diagnostic, disabled by default | `measurement` | ODB ID `31`, whole liters |
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
| Brush timer remaining | `M:SS` | disabled by default | none | `set:ste.app.brushTimer:remainingMilliseconds`; locally counts down once `ste.app.brushTimer:activation` is active and resets to the configured duration after reset/expiry |
| Shower timer remaining | `M:SS` | disabled by default | none | `set:ste.app.showerTimer:remainingMilliseconds`; locally counts down once `ste.app.showerTimer:activation` is active and resets to the configured duration after reset/expiry |
| Wellness runtime (normalized) | `%` | diagnostic, disabled by default | none | ODB ID `32` (`ODB_Wellness_Zeit_Norm`) exposed as the raw normalized runtime value; startup/entity-enable readback `0` placeholders are ignored so the entity stays `unknown` until a real runtime value arrives |
| Reconnects | count | diagnostic | `total_increasing` | Successful reconnect count after the initial connection |
| Connection state | text | diagnostic | none | Client session state such as `starting`, `connected`, `reconnecting` or `stopped` |
| Next reconnect delay | `s` | diagnostic | none | Current backoff delay before the next reconnect attempt; `0 s` while connected |
| Last reconnect reason | text | diagnostic | none | Last recorded session failure or forced reconnect reason |
| Error status | text | diagnostic | none | General error status, including target temperature below inlet temperature and DHE status code `34` service-required state |
| Device info | text | diagnostic, disabled by default | none | DHE version and device information commands; diagnostics export redacts private identifiers |
| Product ID | text | diagnostic, disabled by default | none | Full `set:ste.common.version:gadgetData.id` shown in the Home Assistant UI; diagnostics export still redacts private identifiers |
| WLAN MAC | text | diagnostic, disabled by default | none | `set:ste.common.version:gadgetData.wlan` |
| Bluetooth MAC | text | diagnostic, disabled by default | none | `set:ste.common.version:gadgetData.bluetooth` |

Consumption sensors expose the DHE chart array as a `chart` attribute and the reported cost as `cost_eur` where available. Saving monitor sensors expose the latest `possible`, `real`, `consumption` and `activation_rate` payloads as attributes. Timer remaining sensors mirror the DHE web interface by counting down locally between DHE timer events while the matching timer activation is on; reset, expiry and duration changes restore the remaining value to the configured timer duration. Large chart and catalog payloads are deduplicated before entity writes so repeated DHE messages do not continuously grow the recorder database.

The browser UI exposes ODB IDs `29` (`ODB_Heizen_Energie`), `30` (`ODB_WW_Volumen`), `63` (`ODB_Gsprt_Energie`) and `64` (`ODB_Gsprt_KW_Volumen`) separately from the `ste.app.consumption:*` and `ste.app.savingMonitor:*` app payloads. The DHE web app labels saving-monitor `possible` as potential saving and saving-monitor `real` as actual saving. Live comparison shows ODB ID `63` tracking the saving-monitor possible energy value, while ODB ID `64` tracks the saving-monitor real water-saving value, so the Home Assistant entities are named by meaning and the protocol source is kept in this reference. ODB ID `30` remains the raw DHE hot-water volume value and is not a saving-monitor entity even when its current value is close to one of the saving-monitor water values. These ODB values stay disabled by default because they are diagnostic protocol values. A `0` returned only as the direct answer to a startup or entity-enable read request is ignored for these IDs; while the DHE connection is active they remain available with an `unknown` state until a real runtime value arrives. On a fresh install or after enabling the entity for the first time, this can last until the next actual water-use/runtime event, after which the DHE usually publishes the value promptly. A later DHE runtime update with value `0` is still accepted.

## Numbers

| Entity | Unit | Range | Mode | Source / command |
|---|---:|---:|---|---|
| Bath fill target volume | `L` | `5` to `200`, step `1` | slider | ODB ID `3`, shown as whole liters |
| Child safety temperature limit | `C` | `20` to configured internal scald-protection limit, step `0.5` | slider | ODB ID `5`, sent as raw tenths |
| Eco flow limit | `L/min` | `4` to `15`, step `0.5` | slider | ODB ID `7`, sent as raw tenths |
| Brush timer duration | `s` | `60` to `1200`, step `1` | box | `assign:ste.app.brushTimer:durationMilliseconds`; shown in Home Assistant as seconds |
| Shower timer duration | `s` | `60` to `1200`, step `1` | box | `assign:ste.app.showerTimer:durationMilliseconds`; shown in Home Assistant as seconds |
| Temperature memory 1-12 temperature | `C` | `20` to `60` | box | `assign:ste.common.temperature:memory`, memory ID `0` to `11`; slots 3 to 12 disabled by default |

Temperature memory writes keep the existing memory name and send `operation: add_change`. Slots 1 and 2 are enabled by default. Slots 3 to 12 are created in the entity registry but disabled by default, so they can be enabled explicitly without cluttering the device configuration card. If an optional slot is enabled before that memory exists on the DHE, its number/text entities can remain `unknown` until the slot is created or written.

Internal scald protection is configured during initial setup and from the integration options under `Connection/device`. The option is local to Home Assistant and should match the physical `Tmax` jumper position.

Currency, electricity price, water price and CO2 emission are configured from the integration options under `Costs & emissions` instead of being exposed as entities. The DHE writes use the same protocol values as the browser UI: currency via `get:ste.common.currency:value`, electricity price via ODB IDs `61`/`70`, water price via ODB IDs `62`/`71` and CO2 emission via ODB ID `69`. Price euro components accept the browser ODB range `0` to `32767`, cent components accept `0` to `99`, and CO2 emission accepts raw `0` to `32767` (`0.000` to `32.767 kg/kWh`).

## Selects

| Entity | Options | Source / command | Behavior |
|---|---|---|---|
| Weather location | weather favorites | `get:ste.app.weather:location` with a `LocationId` value | Selects the active DHE weather favorite |

## Texts

| Entity | Source / command | Behavior |
|---|---|---|
| Temperature memory 1-12 name | `assign:ste.common.temperature:memory`, memory ID `0` to `11` | Renames a memory slot; slots 3 to 12 disabled by default |
| DHE device name | `assign:ste.common.version:controlunitName`, max 30 characters | Renames the DHE device/control-unit name from the diagnostic entity section |

Temperature memory name writes use the current cached or freshly read memory temperature and send `operation: add_change`. Name fields for slots 3 to 12 are disabled by default and can be enabled when those optional memories are used. Leave unused optional slots disabled to avoid `unknown` entities for memory positions the DHE has not created.

## Switches

| Entity | Source / command | Behavior |
|---|---|---|
| Eco mode | ODB ID `6` | Turns Eco mode on or off |
| Bath fill | ODB ID `1` | Starts or stops bath filling |
| Child safety | ODB ID `4` | Enables or disables the child-safety temperature limit |
| Brush timer | `assign:ste.app.brushTimer:activation` | Starts or stops the brush timer |
| Shower timer | `assign:ste.app.showerTimer:activation` | Starts or stops the shower timer |
| Cold prevention | ODB ID `2` value `1`, trigger ODB ID `10` | Starts wellness cold prevention, off sends stop |
| Winter refresh | ODB ID `2` value `2`, trigger ODB ID `10` | Starts winter refresh, off sends stop |
| Summer fitness | ODB ID `2` value `3`, trigger ODB ID `10` | Starts summer fitness, off sends stop |
| Circulation support | ODB ID `2` value `4`, trigger ODB ID `10` | Starts circulation support, off sends stop |

Wellness programs are triggered by writing the program ID and then sending ODB ID `10`. The integration derives switch state from the latest program and active-state readbacks. The switch entity IDs stay stable, but the displayed program name and attributes are refreshed from the DHE `ste.app.wellness:programs` catalog when it is available. The catalog can include `coldwater`, `hot_temperature` and `cold_temperature`; `coldwater=true` means the DHE program contains a cold-water phase where heating is disabled by the device.

## Buttons

| Entity | Command | Behavior |
|---|---|---|
| Reset brush timer | `assign:ste.app.brushTimer:reset` | Resets brush timer remaining time to the configured duration and turns activation off; disabled by default |
| Reset shower timer | `assign:ste.app.showerTimer:reset` | Resets shower timer remaining time to the configured duration and turns activation off; disabled by default |
| Repair pairing | local token reset and reconnect | Deletes the stored DHE token, starts a fresh pairing attempt and asks the user to confirm pairing on the DHE; disabled by default |
| Disconnect radio pairing | `assign:ste.app.radio:paired` with `false` | Sends the observed DHE radio pairing disconnect action |
| Temperature memory 1-12 | ODB ID `66` command | Sends the temperature stored in the matching memory slot; slots 3 to 12 disabled by default |
| Delete temperature memory 3-12 | `assign:ste.common.temperature:memory` | Deletes the matching memory slot with `operation: delete`; disabled by default; memory slots 1 and 2 are fixed presets and are not deletable |

The memory preset buttons do not send fixed temperatures. They read the current memory slot value from the DHE cache, refresh it if needed, build the ODB ID `66` button payload from that temperature and send it.
