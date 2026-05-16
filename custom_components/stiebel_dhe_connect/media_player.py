"""Media player platform for Stiebel DHE Connect."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.media_player import MediaPlayerEntity

try:
    from homeassistant.components.media_player import MediaPlayerEntityFeature
except ImportError:  # pragma: no cover - compatibility with older HA versions
    from homeassistant.components.media_player.const import MediaPlayerEntityFeature

try:
    from homeassistant.components.media_player import MediaPlayerState
except ImportError:  # pragma: no cover - compatibility with older HA versions
    try:
        from homeassistant.components.media_player.const import MediaPlayerState
    except ImportError:  # pragma: no cover - compatibility with much older HA versions
        MediaPlayerState = None

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import DHEClient, DHEError
from .entity_helpers import StiebelDHEEntityMixin
from .entity_state_helpers import connected_and_ready
from . import radio_mapping as radio
from .runtime_helpers import get_runtime_data

_LOGGER = logging.getLogger(__name__)

STATE_IDLE = MediaPlayerState.IDLE if MediaPlayerState is not None else "idle"
STATE_PAUSED = MediaPlayerState.PAUSED if MediaPlayerState is not None else "paused"
STATE_PLAYING = MediaPlayerState.PLAYING if MediaPlayerState is not None else "playing"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DHE media players from a config entry."""
    runtime = get_runtime_data(hass, entry)
    async_add_entities([
        StiebelDHERadioMediaPlayer(
            entry_id=entry.entry_id,
            name=runtime.name,
            client=runtime.client,
        )
    ])


class StiebelDHERadioMediaPlayer(StiebelDHEEntityMixin, MediaPlayerEntity):
    """Radio media player backed by the DHE app radio protocol."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:radio"
    _attr_should_poll = False
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
    )
    _attr_translation_key = "radio"

    def __init__(self, entry_id: str, name: str, client: DHEClient) -> None:
        """Initialize the radio media player."""
        self._init_dhe_entity(
            entry_id=entry_id,
            key="radio",
            name=name,
            client=client,
        )
        self._attr_available = False
        self._attr_extra_state_attributes = {"radio_path": "ste.app.radio"}
        self._attr_state = None
        self._attr_volume_level = None
        self._have_radio_state = False
        self._sources_by_option: dict[str, dict[str, Any]] = {}

    async def async_added_to_hass(self) -> None:
        """Subscribe to DHE radio updates."""
        self.async_on_remove(self._client.add_radio_callback(self._handle_radio_update))
        self.async_on_remove(
            self._client.add_availability_callback(self._handle_availability_update)
        )
        self._apply_radio_state(self._client.last_radio_state)

    async def async_media_play(self) -> None:
        """Start radio playback."""
        await self._set_playing(True)

    async def async_media_pause(self) -> None:
        """Pause radio playback."""
        await self._set_playing(False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start radio playback."""
        await self.async_media_play()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Pause radio playback."""
        await self.async_media_pause()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set radio volume."""
        try:
            self._attr_volume_level = await self._client.set_radio_volume(volume)
        except DHEError as err:
            _LOGGER.error("Could not set DHE radio volume: %s", err)
            raise
        self._attr_available = True
        self.async_write_ha_state()

    async def async_select_source(self, source: str) -> None:
        """Select a DHE radio favorite."""
        station = self._sources_by_option.get(source)
        if station is None:
            raise HomeAssistantError(f"Unknown DHE radio source: {source}")
        try:
            await self._client.select_radio_station(station)
        except DHEError as err:
            _LOGGER.error("Could not select DHE radio source: %s", err)
            raise
        self._attr_source = source
        self._attr_available = True
        self.async_write_ha_state()

    async def async_media_next_track(self) -> None:
        """Select the next DHE radio favorite."""
        await self._select_relative_source(1)

    async def async_media_previous_track(self) -> None:
        """Select the previous DHE radio favorite."""
        await self._select_relative_source(-1)

    async def _set_playing(self, playing: bool) -> None:
        try:
            self._attr_state = (
                STATE_PLAYING if await self._client.set_radio_play(playing) else STATE_PAUSED
            )
        except DHEError as err:
            _LOGGER.error("Could not set DHE radio playback: %s", err)
            raise
        self._attr_available = True
        self.async_write_ha_state()

    async def _select_relative_source(self, offset: int) -> None:
        sources = list(self._sources_by_option)
        if not sources:
            raise HomeAssistantError("No DHE radio favorites available")
        current_index = self._current_source_index(sources)
        if current_index < 0:
            if offset < 0:
                next_source = sources[-1]
            else:
                next_source = sources[0]
        else:
            next_source = sources[(current_index + offset) % len(sources)]
        await self.async_select_source(next_source)

    def _current_source_index(self, sources: list[str]) -> int:
        if self._attr_source in sources:
            return sources.index(self._attr_source)

        station_id = self._current_station_id()
        if station_id is not None:
            for index, source in enumerate(sources):
                if _station_id(self._sources_by_option[source]) == station_id:
                    return index
        return -1

    def _current_station_id(self) -> int | None:
        content_id = self._attr_media_content_id
        if content_id is None:
            return None
        try:
            return int(content_id)
        except (TypeError, ValueError):
            return None

    @callback
    def _handle_radio_update(self, state: dict[str, Any]) -> None:
        """Handle radio state updates from the persistent client."""
        self._apply_radio_state(state)
        self.async_write_ha_state()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = connected_and_ready(available, self._have_radio_state)
        self.async_write_ha_state()

    def _apply_radio_state(self, state: dict[str, Any]) -> None:
        if state:
            self._have_radio_state = True

        self._apply_playback_state(state)
        self._apply_volume_state(state)

        station = state.get("station")
        if isinstance(station, dict):
            self._apply_station_media(state, station)
        else:
            self._clear_station_media()

        self._apply_source_state(state, station)

        self._attr_extra_state_attributes = radio.radio_attributes(state)
        self._attr_available = connected_and_ready(
            self._client.available,
            self._have_radio_state,
        )

    def _apply_playback_state(self, state: dict[str, Any]) -> None:
        """Apply HA playback state from the DHE radio state."""
        play = state.get("play")
        if play is True:
            self._attr_state = STATE_PLAYING
        elif play is False:
            self._attr_state = STATE_PAUSED
        elif state:
            self._attr_state = STATE_IDLE

    def _apply_volume_state(self, state: dict[str, Any]) -> None:
        """Apply HA volume level from the DHE radio state."""
        volume = state.get("volume")
        if isinstance(volume, (int, float)):
            self._attr_volume_level = max(0.0, min(float(volume) / 100.0, 1.0))

    def _apply_source_state(
        self,
        state: dict[str, Any],
        station: Any,
    ) -> None:
        """Apply source list and active source from the DHE radio state."""
        self._sources_by_option = radio.source_option_map_for_state(
            state,
            self._sources_by_option,
        )
        self._attr_source_list = list(self._sources_by_option)
        self._attr_source = radio.source_for_state(
            station,
            self._sources_by_option,
            self._attr_source,
        )

    def _apply_station_media(
        self,
        state: dict[str, Any],
        station: dict[str, Any],
    ) -> None:
        """Apply station media fields used by the HA media-player controls."""
        current_station_id = radio.station_id(station)
        self._attr_media_content_id = (
            str(current_station_id) if current_station_id is not None else None
        )
        self._attr_media_content_type = "music"
        self._attr_media_image_url = radio.station_logo_url(station)
        self._attr_media_title = radio.media_title(state, station)
        self._attr_media_artist = radio.station_name(station)

    def _clear_station_media(self) -> None:
        """Clear station metadata when the DHE does not publish a station."""
        self._attr_media_content_id = None
        self._attr_media_content_type = None
        self._attr_media_image_url = None
        self._attr_media_title = None
        self._attr_media_artist = None
