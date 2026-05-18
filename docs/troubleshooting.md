# Troubleshooting

This guide collects the checks that are most useful when the DHE Connect
integration does not behave as expected. The integration is local-only, so most
issues come from pairing state, local network reachability, DHE session state or
Home Assistant entity/recorder behavior.

## Quick checks

Start with these checks before changing configuration:

1. Confirm that the DHE web interface opens from the same network as Home Assistant.
2. Confirm that the integration host field contains only a host name or IP address, not a URL.
3. Confirm that the configured port matches the DHE web interface port.
4. Check the `Connection state`, `Reconnects`, `Last reconnect reason` and `Error status` diagnostic sensors.
5. Check Home Assistant logs for `custom_components.stiebel_dhe_connect`.
6. If the issue started after testing development builds, reload the integration once and restart Home Assistant if entities still look stale.

## Pairing Fails Or Repeats

Pairing requires confirmation on the DHE display. If the setup flow reaches the
confirmation step but never completes, check the device display and confirm the
pairing prompt there.

If pairing keeps repeating:

1. Enable the disabled-by-default `Repair pairing` button.
2. Press `Repair pairing`.
3. Confirm the new pairing request on the DHE display.
4. Wait until the `Connection state` diagnostic sensor returns to `connected`.

Manual token deletion is only a fallback when Home Assistant cannot load the
integration far enough to expose the repair button. Token files are stored under:

```text
/config/.storage/stiebel_dhe_connect_token_<host>_<port>.txt
```

With multiple DHE devices, delete only the token file for the affected host and
port.

## Host Or Port Changed

If the DHE address changes, update the integration options or recreate the
config entry with the new host/port pair. Pairing tokens are scoped to the
configured target, so a changed host or port usually needs a fresh pairing.

Use the config flow fields exactly as intended:

- Host: `dhe.local` or an IP address
- Port: `8443` or the port shown by the DHE web interface

Do not enter `http://`, `https://`, paths, query strings, usernames, passwords
or embedded ports in the host field.

## Setup Scan Finds Nothing

When adding the integration, Home Assistant asks whether it should scan a subnet
for DHE-like web interfaces on port `8443`. The scan is enabled by default, but
it is only a setup convenience. Subnet fields are shown only after the scan
option is selected. Home Assistant pre-fills network address and subnet mask
from its current local subnet when possible. Leave all subnet fields empty to
scan the current local subnet, adjust network address `192.168.1.0` plus subnet
mask `255.255.255.0`, or enter CIDR `192.168.1.0/24`; do not fill both
alternatives. If you skip it or it finds nothing, enter the DHE host/IP and port
manually.

Zeroconf/mDNS discovery is normally limited to the local subnet/VLAN. It only
works across subnets when the router or firewall forwards mDNS through a proper
reflector or repeater. If the DHE Connect is reachable by IP but not discovered
automatically, enter the host/IP manually or run the explicit subnet scan for
that network.

If the DHE web interface opens from a browser but the scan does not find it:

1. Confirm that Home Assistant can route to the same DHE subnet.
2. Confirm that port `8443` is reachable from the Home Assistant host.
3. Enter the DHE address manually in the setup form.
4. Continue with the normal pairing confirmation.

## Cannot Connect

When the integration cannot connect:

1. Open the DHE web interface from a browser in the Home Assistant network.
2. Check whether another browser tab, mobile app or automation is keeping the DHE session busy.
3. Confirm that the DHE and Home Assistant can route to each other.
4. Confirm that no firewall blocks the configured port.
5. Reload the integration after the DHE web interface is reachable again.

The integration reconnects automatically after socket closes and short DHE
session drops. Repeated reconnects are visible through the `Reconnects` and
`Last reconnect reason` sensors.

## Entities Stay Unavailable

Entities are live-state based. During reconnects they can become unavailable
until fresh runtime data arrives from the DHE.

For optional entities enabled after startup, reload the integration if the DHE
has not sent the matching value yet. Some disabled-by-default entities depend on
runtime payloads and may stay `unknown` until the device publishes the next real
value.

Diagnostic ODB total and saving sensors use stricter startup handling:

- `Heating energy`
- `Hot water volume`
- `Possible energy saving`
- `Actual water saving`

For these sensors, a direct startup or entity-enable readback of `0` is treated
as a placeholder. The entity stays available with `unknown` until the DHE sends
a real runtime update. A later runtime value of `0` is still accepted.

The ODB saving sensors can be close to saving-monitor sensors, but they are not
the same source. `ODB_Gsprt_Energie` tracks the saving-monitor possible energy
value in observed DHE traffic. `ODB_Gsprt_KW_Volumen` tracks the saving-monitor
real water-saving value. `ODB_WW_Volumen` remains a hot-water-volume ODB value
even when its current value is close to a saving-monitor water value.

The Home Assistant entity names intentionally omit protocol labels such as
`ODB`. The entity reference keeps the exact ODB ID and web-interface name in the
source column for debugging.

## Recorder Writes Too Much

The integration filters repeated high-churn values before writing Home Assistant
state. If the recorder database still grows unexpectedly, separate idle and
operational windows:

```bash
python scripts/ha_test_smoke.py --config /mnt/ha-test-config --include-fault-log --monitor-seconds 90
```

Run the monitor while the DHE is idle when validating database churn. If the
device-status sensor reports water running (`status_2` or the observed
transition state `status_4`), or if `Last usage duration` changes during the
monitor window, the smoke check treats the window as operational and skips idle
write thresholds. It still checks logs and reconnect stability.

Expected operational writers during water use include current flow, current
power, live temperature, consumption and saving-monitor entities. Unexpected idle
writers should be investigated from the top-writer list printed by the smoke
check.

Numeric sensor write filters suppress small jitter, but current flow and current
power still publish visible runtime changes of at least `0.2` and every
transition between `0` and a non-zero value. Timer remaining values and bath-fill
volumes are intentionally unfiltered so they stay live in the UI. If one of
these values appears stuck after an operation starts or stops, treat that as a
stale-state bug rather than expected recorder throttling.

Home Assistant records normal state changes unless the recorder is configured to
exclude the affected entities. If current flow or current power should stay live
in dashboards but not grow the recorder database, exclude the concrete entity
IDs in the Home Assistant recorder configuration. The same applies if optional
timer or bath-fill entities should be visible live but should not keep a
long-term history.

Example, adjusted to the actual entity IDs from your Home Assistant instance:

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

## Weather Favorites

Weather favorite selection mirrors the DHE web interface:

- Search by city and country from the integration options or service call.
- Add or remove favorites through the explicit `add_weather_favorite` and
  `remove_weather_favorite` services when you want idempotent behavior.
- Use `toggle_weather_favorite` only when you intentionally want the native DHE
  toggle behavior.
- Select the active favorite through `Weather location` or
  `select_weather_location`.

When multiple DHE devices are configured, include `entry_id` in service data so
the service targets the intended device.

## Radio Favorites

The radio entity exposes DHE radio favorites as media-player sources. If no
source list or station metadata is visible:

1. Open or change the radio once on the DHE web interface.
2. Reload the integration after the DHE publishes radio metadata.
3. Use the integration options to search and add stations to the DHE favorites.

Radio station catalogs and search results can be large. The integration keeps
those payloads out of repeated recorder-visible attributes unless they are needed
for options flow or entity state.

## Temperature Memory Slots

Temperature memory slots 1 and 2 are fixed presets and enabled by default. Slots
3 to 12 are optional and disabled by default.

If optional memory name, temperature or button entities show `unknown`, the DHE
has probably not created that slot yet. Either keep unused slots disabled or
create/write the slot from Home Assistant or the DHE UI before relying on its
entities.

When multiple devices are configured, memory services should include `entry_id`
if the target device is not otherwise unambiguous.

## Debug Logs

Enable debug logging only while collecting evidence:

```yaml
logger:
  logs:
    custom_components.stiebel_dhe_connect: debug
```

Then restart Home Assistant or reload logging. Disable debug logging again after
capturing the problem so large protocol payloads do not fill logs.

Validation helpers redact private host, token and credential context from their
own output, but Home Assistant backups and raw `.storage` files can still contain
sensitive data. Treat them as private.

## Development Smoke Checks

The complete validation flow is documented in
[validation.md](validation.md). The short version:

For a mounted Home Assistant test configuration:

```bash
python scripts/ha_test_smoke.py --config /mnt/ha-test-config --include-fault-log
```

For live service smoke against a test instance:

```bash
HA_TEST_URL=http://homeassistant.local:8123 \
HA_TEST_USERNAME=your-ha-user \
HA_TEST_PASSWORD=your-ha-password \
python scripts/ha_test_api.py --config /mnt/ha-test-config --service-smoke --cleanup-localhost-tokens
```

Do not run service smoke while someone depends on hot water. The service smoke
actively calls `climate.turn_off`, `climate.turn_on`, `media_player.turn_off`
and `media_player.select_source`.
