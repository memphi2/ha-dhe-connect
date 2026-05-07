# Stiebel DHE Connect

Local Home Assistant integration for Stiebel Eltron DHE Connect instantaneous water heaters.

Repository: `memphi2/ha-dhe-connect`.

## Version 0.7.9

This release fixes temperature memory runtime handling after the 0.7.8 control release.

## Functionality

- Local Socket.IO / Engine.IO v3 long-polling connection to the DHE.
- Target-temperature climate control.
- Sensors for current water flow, current power, configured power and DHE app consumption charts.
- Controls for Eco mode, Eco flow limit, maximum temperature and bath fill.
- Brush timer and shower timer switches, duration numbers, remaining sensors and reset buttons.
- Temperature memory preset buttons and configurable memory temperatures.
- Temperature memory writes handle both list and single-object memory responses.
- Optional web UI startup reads stay best-effort so the live DHE session can continue.
- Wellness program switches for cold prevention,winter refresh, summer fitness and circulation support.
- English and German Home Assistant translations.

