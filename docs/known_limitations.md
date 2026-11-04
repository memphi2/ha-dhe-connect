# Known Limitations

- Local network only: no cloud relay and no remote vendor API path.
- This integration line requires Home Assistant `2026.10.4` or newer. Older HA
  installations need a release with a matching minimum; see [installation.md](installation.md).
- Discovery depends on mDNS visibility. Across VLANs/subnets, router mDNS
  reflection/relay must be configured.
- Setup subnet scan is intentionally limited to private IPv4 ranges and bounded
  subnet sizes.
- Firmware payloads can differ between device families and versions; optional
  fields may appear/disappear without prior notice.
- Some optional diagnostic values are only available after matching runtime
  events and may start as `unknown`.
- This integration is based on observed local interoperability behavior and is
  not an official manufacturer API.
- No manufacturer support is provided through this repository.

Direct unicast hostname resolution alone does not create a Zeroconf flow prompt.
If multicast discovery is unavailable, use manual host/port setup instead.
