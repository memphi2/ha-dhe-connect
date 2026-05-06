# DHE App Timer Protocol

This document records the observed local Socket.IO / Engine.IO message format for the DHE app timers.

## Timer paths

| Timer | Path |
|---|---|
| Brush timer | `ste.app.brushTimer` |
| Shower timer | `ste.app.showerTimer` |

## Activation commands

| Purpose | Outbound command | Value |
|---|---|---|
| Start brush timer | `assign:ste.app.brushTimer:activation` | `true` |
| Stop brush timer | `assign:ste.app.brushTimer:activation` | `false` |
| Start shower timer | `assign:ste.app.showerTimer:activation` | `true` |
| Stop shower timer | `assign:ste.app.showerTimer:activation` | `false` |

Outbound app timer write messages use the same Socket.IO message-id prefix as the DHE web UI:

```text
42/1.0.0,<message_id>["message",{"command":"assign:ste.app.showerTimer:activation","value":true}]
```

Example:

```text
42/1.0.0,79["message",{"command":"assign:ste.app.showerTimer:activation","value":true}]
```

## Confirmation messages

The DHE can confirm activation changes as `set:` messages without a message id:

```text
42/1.0.0,["message",{"command":"set:ste.app.showerTimer:activation","value":true}]
```

The same structure is used for brush timer confirmations and for `false` values.

## Home Assistant entities

The integration exposes the app timers as:

- activation switches for start and stop
- duration number entities, maximum `20 min`
- explicit start buttons
- reset buttons
- remaining-time sensors displayed as `M:SS`

Separate stop button entities are intentionally not exposed because the activation switches already cover stop behavior.
