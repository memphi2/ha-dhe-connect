# DHE App Timer Protocol

This note documents the observed local Socket.IO / Engine.IO message format for the DHE app timers.

## Scope

The timer remaining sensors stay part of the integration:

- `Brush timer remaining`
- `Shower timer remaining`

They are fed by the DHE app timer `remainingMilliseconds` values and are displayed in Home Assistant as minutes.

## Timer activation

The brush timer and shower timer are started and stopped through the `activation` property.

| Purpose | Outbound command | Value |
|---|---|---|
| Start shower timer | `assign:ste.app.showerTimer:activation` | `true` |
| Stop shower timer | `assign:ste.app.showerTimer:activation` | `false` |
| Start brush timer | `assign:ste.app.brushTimer:activation` | `true` |
| Stop brush timer | `assign:ste.app.brushTimer:activation` | `false` |

## Wire format

Outbound app timer write messages use the same Socket.IO message-id prefix as the DHE web UI:

```text
42/1.0.0,<message_id>["message",{"command":"assign:ste.app.showerTimer:activation","value":true}]
```

Example shower timer start:

```text
42/1.0.0,79["message",{"command":"assign:ste.app.showerTimer:activation","value":true}]
```

Example brush timer start:

```text
42/1.0.0,80["message",{"command":"assign:ste.app.brushTimer:activation","value":true}]
```

The DHE confirmation is observed as a `set:` message without a message id:

```text
42/1.0.0,["message",{"command":"set:ste.app.showerTimer:activation","value":true}]
```

```text
42/1.0.0,["message",{"command":"set:ste.app.brushTimer:activation","value":true}]
```

The same structure applies to `false` confirmations when a timer is stopped.

## Home Assistant representation

The integration keeps the following Home Assistant timer entities:

- Brush timer activation switch, icon `mdi:toothbrush`
- Shower timer activation switch, icon `mdi:shower-head`
- Brush timer duration number
- Shower timer duration number
- Brush timer remaining sensor
- Shower timer remaining sensor
- Brush timer reset button
- Shower timer reset button
