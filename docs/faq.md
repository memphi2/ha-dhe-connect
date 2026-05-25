# FAQ

## Zeroconf finds nothing

Use manual host/port setup or subnet scan. Zeroconf usually needs mDNS
visibility in the same subnet/VLAN.

See: [troubleshooting.md](troubleshooting.md#zeroconf-finds-nothing)

## Setup scan finds nothing

Check selected subnet and scan port (`8443` default).

See: [troubleshooting.md](troubleshooting.md#setup-scan-finds-nothing)

## DHE is connected but entities are unavailable

Check connection diagnostics and reconnect state. After grace timeout, live
entities stay unavailable until fresh runtime data arrives.

See: [troubleshooting.md](troubleshooting.md#dhe-offline)

## Token invalid / pairing required

Use `Repair pairing` and confirm pairing on the device display.

See: [troubleshooting.md](troubleshooting.md#pairing-required--token-invalid--repairs)

## Reconfigure host/port without new entry

Use the Reconfigure flow on the existing integration entry.

See: [troubleshooting.md](troubleshooting.md#reconfigure-host-or-port)

## Recorder grows too fast

Enable only needed high-churn entities and validate recorder writes with mounted
smoke checks.

See: [troubleshooting.md](troubleshooting.md#recorder-writes-too-much)

## Radio or weather behavior looks inconsistent

Check favorites and active source/location sync.

See:

- [troubleshooting.md](troubleshooting.md#radio-or-weather-missing)
- [troubleshooting.md](troubleshooting.md#weather-favorites)
- [troubleshooting.md](troubleshooting.md#radio-favorites)
