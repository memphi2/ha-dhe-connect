# Use Cases

## Family Bathroom / Scald Protection

- Keep a fixed physical `Tmax` jumper profile in Home Assistant options.
- Use child safety and bath fill controls with dashboard visibility.
- Add a simple automation for timer completion notifications.

## Energy Monitoring

- Track current power and water flow during peak usage windows.
- Use total water/energy sensors for monthly utility overview dashboards.
- Keep high-frequency diagnostics disabled if recorder growth is a concern.

## Eco / Comfort Operation

- Schedule `Eco mode` for night hours.
- Keep daytime comfort by switching Eco mode off in the morning.
- Combine with target temperature presets for routine operation.

## Vacation Home / Secondary Location

- Keep one dedicated config entry per physical device.
- Use Reconfigure when host or port changes after router replacement.
- Use Repairs flow if pairing/token state is lost after device reset.

## DHE Radio / Weather in Bathroom

- Use the radio media player and weather entity exposed by the integration.
- Keep favorites in sync through options flow and service actions.
- Use entity-based cards for quick source/favorite switching.

## Multi-DHE Household

- Add one config entry per DHE.
- Use `entry_id` in service calls when more than one DHE is configured.
- Keep names explicit (`Main Bath`, `Guest Bath`) for clear automation targets.

## Tablet / Wall Dashboard

- Show connection status, current power, current flow and controls on one panel.
- Include only frequently used controls in the default view.
- Keep diagnostics entities available for support and troubleshooting views.
