# Known Limitations

- Local network only: no cloud relay and no remote vendor API path.
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
- Discovery across routed subnets requires network infrastructure support
  (mDNS reflector/repeater); direct unicast hostname resolution alone is not
  enough for Home Assistant Zeroconf flow prompts.
