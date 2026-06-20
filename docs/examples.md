# Automation Examples

These examples are intentionally compact and use stable entities from this
integration. Replace entity IDs with your own registry IDs.

## Shower Timer Finished Notification

```yaml
alias: DHE shower timer finished
triggers:
  - trigger: state
    entity_id: sensor.dhe_connect_shower_timer_remaining
    to: "0"
conditions:
  - condition: state
    entity_id: switch.dhe_connect_shower_timer
    state: "on"
actions:
  - action: notify.mobile_app_phone
    data:
      title: DHE
      message: Shower timer finished.
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
    entity_id: sensor.dhe_connect_connection_state
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
