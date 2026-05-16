# Security Policy

## Scope

This integration is intended for local use inside a trusted Home Assistant network. It talks directly to the local DHE web interface via HTTP and Socket.IO/Engine.IO transport (long-polling with WebSocket upgrade).

## Recommendations

- Do not expose the DHE web interface or port `8443` to the internet.
- Keep Home Assistant and HACS updated.
- Treat debug logs as sensitive if they contain raw protocol frames.
- Remove the matching `/config/.storage/stiebel_dhe_connect_token_<host>_<port>.txt` file to revoke the local integration token and pair again.
- Restrict access to Home Assistant backups because the token file is included in the HA config directory.

## Token handling

The integration stores the DHE token locally per configured DHE target at:

```text
/config/.storage/stiebel_dhe_connect_token_<host>_<port>.txt
```

Older integration versions used `/config/.storage/stiebel_dhe_connect_token.txt` or entry-id based token filenames. Setup pairing removes stale legacy token files that are not owned by an existing config entry before requesting a fresh token.

The file is written atomically and the integration attempts to set permissions to `0600`. Some Home Assistant filesystems may not enforce POSIX permissions; therefore Home Assistant backups and config access should be treated as sensitive.

## Reporting issues

Please report security-related issues through GitHub issues:
[https://github.com/memphi2/ha-dhe-connect/issues](https://github.com/memphi2/ha-dhe-connect/issues)
