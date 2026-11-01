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

Only legacy per-target files generated for a host and port are migration inputs:
`.storage/stiebel_dhe_connect_token_<normalized-host>_<port>.txt`. Setup checks
the reachable target and the entry's configured target candidates. Retargeting
checks the destination before the old target. An existing well-formed config-entry
token takes precedence; otherwise the first well-formed candidate is stored.
Well-formed source files are retained until the next Home Assistant start loads
both the token and a migration marker from the persisted config entry. An
integration reload alone does not delete them. This avoids losing the last
durable token if HA crashes before its delayed config-entry write. The marker
contains only legacy filenames, not a second token, and is removed after cleanup.
Retained and in-flight sources remain protected from unrelated setup cleanup.
Malformed candidates can be removed immediately. Explicit pairing recovery
also clears all candidates of overlapping migrations, including files not yet
read or recorded in the migration marker, so they cannot restore a deliberately
removed credential. A reset preserves tokens saved after it began, even when
another reset is still pending.
Deleting an old file does not clear the active token in the config entry.

Entry-ID-based or shared files from private/development snapshots are not
automatically imported. Use the pairing recovery flow for those installations.
Setup can separately clean up unconfigured files matching the legacy per-target
filename prefix; that cleanup is not a migration of their contents.

Use `Repair pairing` or the fixable pairing/token issue in Repairs to request a
fresh pairing. The pairing procedure may require confirmation on the DHE.
Removing a stored token or the integration's config entry removes the local
credential; it must not be treated as proof that the DHE has revoked it. If a
token may have been disclosed, invalidate its authorization on the device using
the device's supported controls, then pair again. See the
[pairing troubleshooting guide](docs/troubleshooting.md#pairing-required--token-invalid--repairs).

## Diagnostic redaction

Runtime diagnostics, HA smoke checks and release validation redact known token, authorization, credential, URL and private-host fragments before printing failures. This is a defense-in-depth measure for support logs and CI output; it is not a substitute for protecting Home Assistant config storage and backups.

Internal polling and WebSocket session identifiers are not published as entity
attributes. Device HTTP requests and WebSocket handshakes refuse redirects.
Protocol responses and WebSocket messages are limited to 4 MiB; the optional web
version and setup reachability probes are limited to 256 KiB. HTTP requests ask for uncompressed responses
and reject unexpected compression before decoding. HTTP error bodies are not
included in transport errors.

## Reporting vulnerabilities

Report suspected vulnerabilities privately using
[GitHub private vulnerability reporting](https://github.com/memphi2/ha-dhe-connect/security/advisories/new).
Do not disclose an unfixed vulnerability in a public issue or pull request.
Include affected versions, reproducible steps and the impact. Use synthetic
credentials and redact tokens, private addresses and personal information from
any attachments; never upload raw Home Assistant storage or backups.

Ordinary bugs and feature requests belong in
[GitHub issues](https://github.com/memphi2/ha-dhe-connect/issues).
