# Security Policy

## Scope

This integration is intended for local use inside a trusted Home Assistant network. It talks directly to the local DHE web interface via HTTP and Socket.IO/Engine.IO long-polling.

## Recommendations

- Do not expose the DHE web interface or port `8443` to the internet.
- Keep Home Assistant and HACS updated.
- Treat debug logs as sensitive if they contain raw protocol frames.
- Remove `/config/.storage/stiebel_dhe_connect_token.txt` to revoke the local integration token and pair again.
- Restrict access to Home Assistant backups because the token file is included in the HA config directory.

## Token handling

The integration stores the DHE token locally at:

```text
/config/.storage/stiebel_dhe_connect_token.txt
```

The file is written atomically and the integration attempts to set permissions to `0600`. Some Home Assistant filesystems may not enforce POSIX permissions; therefore Home Assistant backups and config access should be treated as sensitive.

## Reporting issues

Bitte Issues über GitHub melden: https://github.com/memphi2/ha-dhe-connect/issues
