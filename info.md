# Stiebel DHE Connect

Local Home Assistant integration for Stiebel Eltron DHE Connect instantaneous water heaters.

Repository: `memphi2/ha-dhe-connect`.

## Version 0.7.6

This release keeps switch-based controls and adds dedicated wellness program switches with on/off behavior.

## Functionality

- Local Socket.IO / Engine.IO v3 long-polling connection to the DHE.
- Target-temperature climate control.
- Sensors for current water flow, current power, configured power and DHE app consumption charts.
- Controls for Eco mode, Eco flow limit, maximum temperature and bath fill.
- Brush timer and shower timer switches, duration numbers, remaining sensors and reset buttons.
- Wellness cold prevention switch plus wellness program switches for winter refresh, summer fitness and circulation support.
- Timer durations are limited to `20 min`.
- Timer remaining sensors are displayed as `M:SS`.
- English and German Home Assistant translations.
- Brand icons in `brand/icon.png` and `brand/dark_icon.png`.
