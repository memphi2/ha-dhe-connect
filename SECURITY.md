# Security Policy

## Scope

This integration is intended for local use inside a trusted Home Assistant network. It talks directly to the local DHE web interface via HTTP and Socket.IO/Engine.IO transport (long-polling with WebSocket upgrade).

## Recommendations

- Do not expose the DHE web interface or port `8443` to the internet.
- Keep Home Assistant and the integration updated through the Marketplace.
  If the installation is still HACS-managed, keep HACS updated too.
- Treat debug logs as sensitive if they contain raw protocol frames.
- Use the integration's `Repair pairing` button or the Home Assistant Repairs flow to replace a rejected token. Do not edit Home Assistant storage by hand.
- Restrict access to Home Assistant configuration and backups because they contain the stored pairing token.
- Avoid sharing mounted Home Assistant config folders, release-check logs or smoke-test output without reviewing them first.

## Token handling

The integration stores the DHE pairing token in the data of its Home Assistant
config entry. Home Assistant manages persistence in `.storage/core.config_entries`;
the integration does not create a separate token file for normal operation.
Treat that storage and all backups containing it as credentials. Never share raw
config-entry storage, and do not edit it manually.

Legacy per-target, entry-id and shared token files are migration inputs only.
Setup and retargeting migrate a usable legacy token into the config entry, then
delete the legacy files. Deleting an old file after migration does not clear the
active token in the config entry.

Use `Repair pairing` or the fixable pairing/token issue in Repairs to request a
fresh pairing. The pairing procedure may require confirmation on the DHE.
Removing a stored token or the integration's config entry removes the local
credential; it must not be treated as proof that the DHE has revoked it. If a
token may have been disclosed, invalidate its authorization on the device using
the device's supported controls, then pair again. See the
[pairing troubleshooting guide](docs/troubleshooting.md#pairing-required--token-invalid--repairs).

## Diagnostic redaction

Runtime diagnostics, HA smoke checks and release validation redact known token, authorization, credential, URL and private-host fragments before printing failures. This is a defense-in-depth measure for support logs and CI output; it is not a substitute for protecting Home Assistant config storage and backups.

## Reporting vulnerabilities

Report suspected vulnerabilities privately using
[GitHub private vulnerability reporting](https://github.com/memphi2/ha-dhe-connect/security/advisories/new).
Do not disclose an unfixed vulnerability in a public issue or pull request.
Include affected versions, reproducible steps and the impact. Use synthetic
credentials and redact tokens, private addresses and personal information from
any attachments; never upload raw Home Assistant storage or backups.

Ordinary bugs and feature requests belong in
[GitHub issues](https://github.com/memphi2/ha-dhe-connect/issues).
