# Stiebel DHE Connect

Local Home Assistant integration for Stiebel Eltron DHE Connect instantaneous water heaters.

Repository: `memphi2/ha-dhe-connect`.

## Version 0.7.10

This release optimizes the runtime client and requests all currently known web UI startup values best-effort.

## Functionality

- Local Socket.IO / Engine.IO v3 long-polling connection to the DHE.
- Best-effort startup reads for currently known DHE web UI values without extra entities.
- Target-temperature climate control.
- Sensors for current water flow, current power, configured power and DHE app consumption charts.
- Controls for Eco mode, Eco flow limit, maximum temperature and bath fill.
- Brush timer and shower timer switches, duration numbers, remaining sensors and reset buttons.
- Temperature memory preset buttons for DHE memory slots 1 and 2.
- Temperature memory box inputs for stored memory temperatures.
- Box inputs for brush and shower timer durations.
- Wellness program switches for cold prevention,winter refresh, summer fitness and circulation support.
- English and German Home Assistant translations.

