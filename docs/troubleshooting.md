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

## Pairing Required / Token Invalid / Repairs

Symptoms that usually point to an invalid or stale token:

- The DHE web interface is reachable, but Home Assistant cannot authenticate.
- The integration repeatedly enters reconnect or pairing-related errors after a
  DHE reset, host/port change or restored Home Assistant backup.
- The `Error status` diagnostic sensor reports authentication or token-related
  failures while basic network connectivity is fine.

Use the Home Assistant Repairs issue first when it appears. The repair flow
requests and validates a fresh local pairing token, then reloads the existing
config entry. Confirm the pairing request on the DHE display when prompted.
Depending on runtime diagnostics, the issue title can be either
`DHE pairing needs repair` or `DHE token is invalid`; both use the same repair
flow and require confirmation on the DHE display.

If Home Assistant is loaded but no Repairs issue is visible yet, the
disabled-by-default `Repair pairing` button remains available as a manual
fallback. It removes the token for the affected config entry and starts a fresh
pairing round without requiring manual file edits.

If Home Assistant can still load the config entry and the DHE explicitly stops
accepting the stored token, the integration starts Home Assistant's
reauthentication flow and creates a fixable Repairs issue. Follow either the
reauthentication form or the Repairs form, then confirm the new pairing request
on the DHE display. The integration reloads after successful pairing and login.

Manual token deletion is only a fallback when Home Assistant cannot load the
integration far enough to expose the repair button. Token files are stored under:

```text
/config/.storage/stiebel_dhe_connect_token_<host>_<port>.txt
```

With multiple DHE devices, delete only the token file for the affected host and
port. Never paste token files, `.storage` contents or raw diagnostics into public
issues.

## Pairing Required Again

Pairing is required again when the DHE no longer accepts the stored local token
or after device-side pairing state was reset. A Home Assistant host/port
Reconfigure keeps the existing local token and only leads to repair pairing if
the DHE rejects that token after reload.
The integration does not create a config entry until pairing and login both
succeed.

Use this sequence:

1. Open the Home Assistant Repairs issue for the affected DHE entry.
2. Start the repair flow.
3. Confirm the new pairing request on the DHE display.
4. Wait until the `Connection state` diagnostic sensor returns to `connected`.

If the entry is loaded but the Repairs issue is not visible, use the
disabled-by-default `Repair pairing` button as a fallback.

If pairing is not shown on the DHE display, check that the DHE web interface is
reachable from the Home Assistant network and that no other client keeps the DHE
session busy.

## Device Unreachable During Repair

If the Repairs flow is opened while the DHE target is offline or unreachable,
the flow keeps the issue open and shows `cannot_connect`.

Use this sequence:

1. Verify host and port in the integration entry.
2. Confirm the DHE web interface is reachable from the Home Assistant host.
3. If host/port changed, run `Reconfigure` first and save the reachable target.
4. Start the Repairs flow again and confirm pairing on the DHE display.

## Pairing Fails Or Repeats

Pairing requires confirmation on the DHE display. If the setup flow reaches the
confirmation step but never completes, check the device display and confirm the
pairing prompt there.

If pairing keeps repeating:

1. Enable the disabled-by-default `Repair pairing` button.
2. Press `Repair pairing`.
3. Confirm the new pairing request on the DHE display.
4. Wait until the `Connection state` diagnostic sensor returns to `connected`.

## Reconfigure Host Or Port

If the DHE address changes, use Home Assistant's Reconfigure action for the
DHE Connect config entry. Reconfigure updates the existing config entry instead
of creating a replacement, so entity IDs and unique IDs stay stable. When the
configured host or port changes, Home Assistant checks that the new target is
reachable and copies the existing local token to the new target path. A fresh
pairing is only needed later if the DHE rejects that token.
If the configured target cannot be reached during setup/retry, Home Assistant
raises `Configured DHE host is unreachable`.

Use the config flow fields exactly as intended:

- Host: `dhe.local` or an IP address
- Port: `8443` or the port shown by the DHE web interface

Do not enter `http://`, `https://`, paths, query strings, usernames, passwords
or embedded ports in the host field.

When only the device name or physical Tmax jumper position changes, Reconfigure
saves the updated options without a network check. When host or port changes,
the new target must be reachable before Home Assistant saves the options.

## Zeroconf Finds Nothing

Zeroconf/mDNS discovery is an automatic setup convenience. It depends on
multicast DNS-SD traffic reaching Home Assistant. A DHE can be reachable by IP
while still not appearing in Home Assistant's Zeroconf flow.

Check these points first:

1. Confirm that Home Assistant and the DHE are in the same subnet/VLAN, or that
   the router forwards mDNS with a proper reflector or repeater.
2. Confirm that the DHE advertises `_ste-dhe._tcp.local.` on the network segment
   where Home Assistant listens.
3. Restarting Home Assistant can refresh the discovery cache, but it should not
   be required for manual setup or subnet scan.
4. If the DHE is reachable by IP but not discovered, use `Subnet scan` or
   `Enter manually`.

A direct `.local` hostname lookup or direct unicast DNS-SD answer from the DHE
does not create a Home Assistant Zeroconf discovery by itself. Home Assistant
must receive the multicast advertisement.

For release validation or local evidence collection, run the optional real
Zeroconf/mDNS smoke from a network segment that should receive the multicast
advertisement:

```bash
python scripts/zeroconf_smoke.py --timeout 20
```

This check is a release-lab gate, not a universal CI check. It can fail in
VLANs or networks that block mDNS even when the integration and manual setup are
correct.

The integration keeps a temporary anonymized discovery cache in Home Assistant
storage. Support diagnostics expose cache counts, cache age, confidence bands
and prompt-suppression state, but not raw hosts, IP addresses or service names.

## Setup Scan Finds Nothing

When adding the integration, Home Assistant offers discovered Zeroconf/mDNS
entries first, then subnet scan and manual host entry. The scan is only a setup
convenience and checks for DHE-like web interfaces. The scan-port field defaults
to `8443`. It does not create the integration by itself; pairing and login are
still validated before the config entry is saved.

Subnet fields are shown only after the scan option is selected. Home Assistant
pre-fills custom subnet forms from its current local subnet when possible. Use
the current local subnet, enter network address `192.168.1.0` plus subnet mask
`255.255.255.0`, or enter CIDR `192.168.1.0/24`. If you skip the scan or it
finds nothing, enter the DHE host/IP and port manually.

Only change the scan port if the DHE web interface is reachable on a
non-standard port. The scan port affects the setup-time subnet scan only.
Zeroconf discoveries and manual setup keep using the port reported or entered
for the selected target.

If the DHE web interface opens from a browser but the scan does not find it:

1. Confirm that Home Assistant can route to the same DHE subnet.
2. Confirm that port `8443` is reachable from the Home Assistant host.
3. Enter the DHE address manually in the setup form.
4. Continue with the normal pairing confirmation.

The setup scan is intentionally bounded to private IPv4 networks and limited
subnet sizes. If the DHE is outside the selected subnet, the scan should not
find it. Use manual setup for routed networks or unusual lab topologies.

For a focused discovery debug run, set the environment variable
`DHE_CONNECT_DISCOVERY_DEBUG=1` before starting Home Assistant and enable debug
logging for `custom_components.stiebel_dhe_connect`. Disable it again after the
test; it is meant for short evidence collection, not normal operation.

## Duplicate Device / Discovery Conflict

Home Assistant blocks duplicate DHE config entries by normalized host and port
before pairing. After successful pairing, the integration also stores the
paired device MAC address as the config-entry unique ID when the DHE reports
one. Zeroconf, subnet scan and manual setup use the same pairing-confirm path,
so all setup methods get the same unique-ID behavior.
If discovery identity hints are inconsistent, Home Assistant can raise
`DHE discovery conflict detected`. In that case, continue with manual setup
using one stable host/IP and port.

If Zeroconf later finds the same physical device under a changed host/IP, the
integration can update the existing config-entry target only when stable device
identity matches (for example paired WLAN/Bluetooth MAC). It never rewrites a
target on weak host/name hints alone. If the discovered target is already used
by another configured entry, Home Assistant raises a discovery-conflict repair
issue and does not overwrite either entry.

Before successful pairing, the integration does not create a device. If setup is
cancelled or pairing times out, start the flow again and confirm pairing on the
DHE display.

## DHE Offline

When the integration cannot connect:

1. Open the DHE web interface from a browser in the Home Assistant network.
2. Check whether another browser tab, mobile app or automation is keeping the DHE session busy.
3. Confirm that the DHE and Home Assistant can route to each other.
4. Confirm that no firewall blocks the configured port.

During Home Assistant startup or config-entry reload, an unreachable DHE causes
the config entry to wait for retry instead of setting up stale platform state.
If the DHE goes offline after setup, entities become unavailable after the
reconnect grace window and recover when the device responds again.
After the reconnect grace window expires, Home Assistant can raise
`DHE device is unreachable` until connectivity is restored.
Normal DHE controls are blocked while the runtime is unavailable so Home
Assistant does not send stale writes to an offline device. The disabled-by-
default `Repair pairing` button remains available as the recovery exception.
5. Reload the integration after the DHE web interface is reachable again.

If the DHE is powered, reachable from a browser and still shown as offline in
Home Assistant, compare the browser URL with the integration options. The host
field must contain only a host name or IP address, and the port field must
contain the DHE web-interface port.

Temporary DHE restarts, Wi-Fi drops or web-interface restarts can make entities
unavailable for a short time. The integration should recover automatically after
the DHE accepts a new runtime session.

## Reconnect Loops

The integration reconnects automatically after socket closes and short DHE
session drops. Brief drops stay in a reconnect grace window: cached entities can
remain available while the `Connection state` diagnostic sensor reports
`reconnecting`. Repeated reconnects are visible through the `Reconnects`,
`Next reconnect delay` and `Last reconnect reason` sensors.

If reconnects keep increasing:

1. Check whether the DHE web interface is stable in a browser from the Home
   Assistant network.
2. Close additional browser tabs or mobile apps that may compete for the runtime
   session.
3. Check `Last reconnect reason`, `Next reconnect delay` and `Error status`.
4. If a token error is reported, use `Repair pairing` instead of repeatedly
   reloading the integration.
5. If only short socket-close bursts happen while the DHE stays reachable, keep
   the diagnostics; they help distinguish network churn from token failures.

Support diagnostics include the anonymized reconnect-supervisor state: attempts,
delay configuration, grace-window state and whether entities should already be
marked unavailable. This does not expose host, token or credential data.

## Live Sensors Are Empty

Some live sensors are only populated after the DHE sends the matching runtime
payload. A newly enabled optional entity can therefore be `unknown` until the
next real device update arrives. This is expected for values that the DHE does
not include in every startup snapshot.

Check this before treating an empty value as a bug:

1. Confirm that the `Connection state` sensor is `connected`.
2. Check whether the matching feature is active on the DHE web interface.
3. For optional entities enabled after startup, reload the integration once if
   the value existed before but was not delivered to Home Assistant yet.
4. For high-churn live values such as current flow, current power, timer
   remaining values and bath-fill volumes, compare the Home Assistant state with
   the DHE web interface while the feature is actively changing.

Diagnostic ODB total and saving sensors have special startup handling. A direct
startup or entity-enable readback of `0` can be a placeholder, so the entity may
stay available with `unknown` until a real runtime update arrives. Runtime `0`
values are accepted once the DHE actually publishes them. On a fresh install or
after enabling one of these entities for the first time, this usually resolves
after the next real water-use/runtime event because the DHE then publishes the
matching total or saving value.

## Entities Stay Unavailable

Entities are live-state based. During short reconnects they keep their cached
state; after the reconnect grace expires they become unavailable until fresh
runtime data arrives from the DHE.

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
a real runtime update. This can be visible on fresh installs before the first
usage event; after water is used, the DHE normally publishes the value promptly.
A later runtime value of `0` is still accepted.

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

For release or performance evidence, prefer a longer idle window:

```bash
python scripts/ha_test_smoke.py --config /mnt/ha-test-config --include-fault-log --monitor-seconds 600
```

Run the monitor while the DHE is idle when validating database churn. If the
device-status sensor reports water running (`status_2` or the observed
transition state `status_4`), if the error-status diagnostic attributes carry
that device status, or if `Last usage duration` changes during the monitor
window, the smoke check treats the window as operational and skips idle write
thresholds. It still checks logs and reconnect stability.

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

## Radio Or Weather Missing

Radio and weather data come from the DHE web interface payloads. If those
entities exist but show no useful data, the DHE may simply not have published
the relevant catalog, favorite or runtime payload yet.

For weather:

1. Open the DHE web interface and check whether a weather favorite is configured
   there.
2. Use the integration options or weather services to search/add a favorite.
3. Select the active favorite with `Weather location` or
   `select_weather_location`.
4. Reload the integration after changing favorites if the entity list was empty.

For radio:

1. Check whether the DHE web interface shows radio favorites.
2. Use the integration options to search/add a station.
3. Select a favorite source from the media-player source list.
4. If the radio was off during startup, the media player should still report
   `off`; station metadata may appear only after the DHE publishes it.

Large radio and weather catalogs are intentionally kept out of normal
recorder-visible attributes. They are used for options flow and services, not as
ever-growing entity attributes.

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

If the mounted entity registry contains DHE entries but none are enabled, the
smoke fails instead of silently trusting stale recorder fallback data. That
usually means Home Assistant has not loaded the integration correctly, or the
registry state is not representative for a live validation run.

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
