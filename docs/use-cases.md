# Use Cases And Automation Patterns

## Family Bathroom / Scald Protection

- Keep physical `Tmax` aligned with integration options.
- Use child safety and bath fill controls in a visible dashboard section.
- Add timer-finished notifications for daily use.

## Energy Monitoring

- Track `sensor.dhe_connect_current_power` and
  `sensor.dhe_connect_current_water_flow` during peak usage.
- Use total water/energy sensors for monthly trend dashboards.
- Keep optional high-churn diagnostics disabled unless needed.

## Eco / Comfort Operation

- Schedule `switch.dhe_connect_eco_mode` for night hours.
- Switch Eco mode off in the morning for comfort.

Example:

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

## Vacation Home / Secondary Location

- Keep one config entry per physical DHE.
- Use Reconfigure if host/port changes after network changes.
- Use Repairs flow for token/pairing recovery after resets.

## DHE Radio / Weather In Bathroom

- Use the radio media player and weather entity from the same device card.
- Keep favorites in sync with options-flow or services.

## Multi-DHE Household

- Add one config entry per DHE.
- Include `entry_id` in service calls when multiple devices exist.
- Keep explicit device names (`Main Bath`, `Guest Bath`) for clean automations.

## Tablet / Wall Dashboard

- Put connection state, power, water flow and key switches on one panel.
- Keep the default view compact; expose diagnostics in a secondary view.

## More Ready-To-Use Examples

For additional automation and card snippets, see [examples.md](examples.md).
