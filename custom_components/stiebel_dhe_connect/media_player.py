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

    @callback
    def _handle_radio_update(self, state: dict[str, Any]) -> None:
        """Handle radio state updates from the persistent client."""
        self._apply_radio_state(state)
        self.async_write_ha_state()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = available or self._have_radio_state
        self.async_write_ha_state()

    def _apply_radio_state(self, state: dict[str, Any]) -> None:
        if state:
            self._have_radio_state = True
            self._attr_available = True

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

        self._attr_extra_state_attributes = _radio_attributes(state)


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

    return attributes


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
