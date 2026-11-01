# Automation Examples

These examples are intentionally compact and use stable entities from this
integration. Replace entity IDs with your own registry IDs and the notification
action with your own mobile-app action. See the [entity reference](entities.md)
for diagnostic states and available controls. Import each automation as its own
automation; dashboard snippets belong in a dashboard, not `automations.yaml`.

## Shower Countdown Reaches Zero

Enable the optional shower timer remaining sensor first. Its state is `m:ss`,
not a numeric count. This example detects the local countdown's last second;
it is not a device-confirmed completion event. A stop, reload, disconnection or
device reset before that transition can prevent the notification. The display
resets to the configured duration afterwards, so do not recheck the timer switch
or the current sensor state in an action condition.

```yaml
alias: DHE shower countdown reaches zero
triggers:
  - trigger: state
    entity_id: sensor.dhe_connect_shower_timer_remaining
    from: "0:01"
    to: "0:00"
actions:
  - action: notify.mobile_app_phone
    data:
      title: DHE
      message: Shower countdown reached zero.
mode: single
```

## Eco Mode Schedule

```yaml
alias: DHE eco mode at night
triggers:
  - trigger: time
    at: "22:30:00"
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.dhe_connect_eco_mode
mode: single
```

```yaml
alias: DHE eco mode off in morning
triggers:
  - trigger: time
    at: "06:30:00"
actions:
  - action: switch.turn_off
    target:
      entity_id: switch.dhe_connect_eco_mode
mode: single
```

## Reconnect Warning Notification

```yaml
alias: DHE reconnect warning
triggers:
  - trigger: state
    entity_id: sensor.dhe_connect_connection_state
    to: reconnecting
conditions:
  - condition: numeric_state
    entity_id: sensor.dhe_connect_reconnects
    above: 3
actions:
  - action: notify.mobile_app_phone
    data:
      title: DHE connection
      message: DHE is reconnecting repeatedly. Check Wi-Fi/network path.
mode: single
```

## Bath Fill Reminder

```yaml
alias: DHE bath fill reached
triggers:
  - trigger: state
    entity_id: switch.dhe_connect_bath_fill
    to: "off"
conditions: []
actions:
  - action: notify.mobile_app_phone
    data:
      title: DHE
      message: Bath fill finished.
mode: single
```

## DHE Offline Notification

```yaml
alias: DHE offline
triggers:
  - trigger: state
    entity_id: sensor.dhe_connect_error_status
    to: disconnected
    for:
      minutes: 2
actions:
  - action: notify.mobile_app_phone
    data:
      title: DHE offline
      message: DHE has been unreachable for at least 2 minutes.
mode: single
```

## Energy Monitoring Example

```yaml
type: history-graph
title: DHE usage
entities:
  - entity: sensor.dhe_connect_current_power
  - entity: sensor.dhe_connect_current_water_flow
hours_to_show: 24
refresh_interval: 60
```

## Simple Dashboard Card Example

```yaml
type: entities
title: DHE Connect
entities:
  - climate.dhe_connect
  - sensor.dhe_connect_connection_state
  - sensor.dhe_connect_current_power
  - sensor.dhe_connect_current_water_flow
  - switch.dhe_connect_eco_mode
  - switch.dhe_connect_bath_fill
```
