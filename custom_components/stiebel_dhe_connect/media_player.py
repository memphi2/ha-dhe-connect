"""Media player platform for Stiebel DHE Connect."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.media_player import MediaPlayerEntity

try:
    from homeassistant.components.media_player import MediaPlayerEntityFeature
except ImportError:  # pragma: no cover - compatibility with older HA versions
    from homeassistant.components.media_player.const import MediaPlayerEntityFeature

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import DHEClient, DHEError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STATE_IDLE = "idle"
STATE_PAUSED = "paused"
STATE_PLAYING = "playing"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DHE media players from a config entry."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        StiebelDHERadioMediaPlayer(
            entry_id=entry.entry_id,
            name=runtime.name,
            client=runtime.client,
        )
    ])


class StiebelDHERadioMediaPlayer(MediaPlayerEntity):
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
        self._attr_unique_id = f"stiebel_dhe_connect_{entry_id}_radio"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, client.host)},
            "manufacturer": "STIEBEL ELTRON",
            "model": "DHE Connect",
            "name": name,
        }
        self._attr_available = False
        self._attr_extra_state_attributes = {"radio_path": "ste.app.radio"}
        self._attr_state = None
        self._attr_volume_level = None
        self._client = client
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
            raise ValueError(f"Unknown DHE radio source: {source}")
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
            raise ValueError("No DHE radio favorites available")
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
        self._attr_available = available and self._have_radio_state
        self.async_write_ha_state()

    def _apply_radio_state(self, state: dict[str, Any]) -> None:
        if state:
            self._have_radio_state = True

        play = state.get("play")
        if play is True:
            self._attr_state = STATE_PLAYING
        elif play is False:
            self._attr_state = STATE_PAUSED
        elif state:
            self._attr_state = STATE_IDLE

        volume = state.get("volume")
        if isinstance(volume, (int, float)):
            self._attr_volume_level = max(0.0, min(float(volume) / 100.0, 1.0))

        station = state.get("station")
        if isinstance(station, dict):
            station_id = _station_id(station)
            self._attr_media_content_id = (
                str(station_id) if station_id is not None else None
            )
            self._attr_media_content_type = "music"
            self._attr_media_image_url = _station_logo_url(station)
            self._attr_media_title = _media_title(state, station)
            self._attr_media_artist = _station_name(station)

        favorites = _stations(state.get("favorites"))
        self._sources_by_option = _source_option_map(favorites)
        self._attr_source_list = list(self._sources_by_option)
        self._attr_source = _source_for_station(station, self._sources_by_option)

        self._attr_extra_state_attributes = _radio_attributes(state)
        self._attr_available = self._client.available and self._have_radio_state


def _radio_attributes(state: dict[str, Any]) -> dict[str, Any]:
    station = state.get("station")
    attributes: dict[str, Any] = {"radio_path": "ste.app.radio"}

    if isinstance(station, dict):
        attributes["station_id"] = _station_id(station)
        attributes["station_name"] = _station_name(station)
        station_city = _station_text(station, "City")
        station_country = _station_text(station, "Country")
        station_genres = station.get("Genres", station.get("genres"))
        if station_city:
            attributes["station_city"] = station_city
        if station_country:
            attributes["station_country"] = station_country
        if isinstance(station_genres, list):
            attributes["station_genres"] = [str(genre) for genre in station_genres]

    for key in ("title", "paired"):
        value = state.get(key)
        if value not in (None, ""):
            attributes[key] = value

    favorites = _stations(state.get("favorites"))
    if favorites:
        attributes["favorite_count"] = len(favorites)
        attributes["favorites"] = [
            {
                "id": _station_id(favorite),
                "name": _station_name(favorite),
            }
            for favorite in favorites
        ]

    return attributes


def _source_option_map(stations: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    labels = [_source_label(station) for station in stations]
    duplicated = {label for label in labels if labels.count(label) > 1}
    options: dict[str, dict[str, Any]] = {}

    for station, label in zip(stations, labels, strict=True):
        station_id = _station_id(station)
        option = label
        if label in duplicated and station_id is not None:
            option = f"{label} ({station_id})"
        options[option] = station
    return options


def _source_for_station(
    station: Any,
    sources_by_option: dict[str, dict[str, Any]],
) -> str | None:
    station_id = _station_id(station)
    if station_id is None:
        return _station_name(station)

    for option, source_station in sources_by_option.items():
        if _station_id(source_station) == station_id:
            return option
    return _station_name(station)


def _source_label(station: dict[str, Any]) -> str:
    return _station_name(station) or "Unknown station"


def _stations(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _media_title(state: dict[str, Any], station: dict[str, Any]) -> str | None:
    title = state.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return _station_name(station)


def _station_name(station: Any) -> str | None:
    if not isinstance(station, dict):
        return None
    name = _station_text(station, "Name")
    if name:
        return name
    station_id = _station_id(station)
    return str(station_id) if station_id is not None else None


def _station_id(station: Any) -> int | None:
    if not isinstance(station, dict):
        return None
    station_id = station.get("Id", station.get("id"))
    try:
        return int(station_id)
    except (TypeError, ValueError):
        return None


def _station_logo_url(station: dict[str, Any]) -> str | None:
    url = (
        _station_text(station, "Logo175Url")
        or _station_text(station, "Logo100Url")
        or _station_text(station, "Logo44Url")
    )
    if url and url.startswith("//"):
        return f"https:{url}"
    return url


def _station_text(station: dict[str, Any], key: str) -> str | None:
    value = station.get(key, station.get(key[:1].lower() + key[1:]))
    if value in (None, ""):
        return None
    return str(value)
