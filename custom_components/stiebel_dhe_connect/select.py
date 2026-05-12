"""Select platform for Stiebel DHE Connect."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import DHEClient, DHEError
from .entity_helpers import StiebelDHEEntityMixin
from .entity_state_helpers import connected_and_ready
from .runtime_helpers import get_runtime_data
from .weather_mapping import weather_location_attributes, weather_location_name

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DHE select entities from a config entry."""
    runtime = get_runtime_data(hass, entry)
    async_add_entities([
        StiebelDHEWeatherLocationSelect(
            entry_id=entry.entry_id,
            name=runtime.name,
            client=runtime.client,
        )
    ])


class StiebelDHEWeatherLocationSelect(StiebelDHEEntityMixin, SelectEntity):
    """Weather location select backed by the DHE weather favorites."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_icon = "mdi:map-marker"
    _attr_should_poll = False
    _attr_translation_key = "weather_location"

    def __init__(self, entry_id: str, name: str, client: DHEClient) -> None:
        """Initialize the weather location select."""
        # Use a dedicated unique_id to avoid clashes with legacy sensor entries
        # from older revisions that used `..._weather_location`.
        self._init_dhe_entity(
            entry_id=entry_id,
            key="weather_location_select",
            name=name,
            client=client,
        )
        self._locations_by_option: dict[str, dict[str, Any]] = {}
        self._have_weather_state = False
        self._attr_available = False
        self._attr_current_option: str | None = None
        self._attr_options: list[str] = []
        self._attr_extra_state_attributes = {"weather_path": "ste.app.weather"}

    async def async_added_to_hass(self) -> None:
        """Subscribe to DHE weather and availability updates."""
        self.async_on_remove(
            self._client.add_weather_callback(self._handle_weather_update)
        )
        self.async_on_remove(
            self._client.add_availability_callback(self._handle_availability_update)
        )
        self._apply_weather_state(self._client.last_weather_state)

    async def async_select_option(self, option: str) -> None:
        """Select a DHE weather favorite."""
        location = self._locations_by_option.get(option)
        if location is None:
            raise ValueError(f"Unknown weather location option: {option}")

        try:
            await self._client.select_weather_location(location)
        except DHEError as err:
            self._attr_available = connected_and_ready(
                self._client.available,
                self._have_weather_state,
            )
            self.async_write_ha_state()
            _LOGGER.error("Could not select DHE weather location: %s", err)
            raise

        self._apply_weather_state(self._client.last_weather_state)
        self.async_write_ha_state()

    @callback
    def _handle_weather_update(self, state: dict[str, Any]) -> None:
        """Handle weather state updates from the persistent client."""
        self._apply_weather_state(state)
        self.async_write_ha_state()

    @callback
    def _handle_availability_update(self, available: bool) -> None:
        """Handle DHE connection availability updates."""
        self._attr_available = connected_and_ready(available, self._have_weather_state)
        self.async_write_ha_state()

    def _apply_weather_state(self, state: dict[str, Any]) -> None:
        location = state.get("location")
        current_location = location if isinstance(location, dict) else None
        favorites = _weather_locations(state.get("favorites"))
        self._locations_by_option = _weather_location_option_map(
            favorites,
            current_location=current_location,
        )
        self._attr_options = list(self._locations_by_option)
        self._attr_current_option = _option_for_location(
            current_location,
            self._locations_by_option,
        )
        self._have_weather_state = current_location is not None or bool(self._attr_options)
        self._attr_available = connected_and_ready(
            self._client.available,
            self._have_weather_state,
        )

        attributes: dict[str, Any] = {
            "weather_path": "ste.app.weather",
            "favorite_count": len(favorites),
        }
        if current_location is not None:
            attributes.update(weather_location_attributes(current_location))
            attributes["is_favorite"] = _location_in_list(current_location, favorites)
        self._attr_extra_state_attributes = attributes


def _weather_locations(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _weather_location_option_map(
    favorites: list[dict[str, Any]],
    *,
    current_location: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    locations = list(favorites)
    if current_location is not None and not _location_in_list(current_location, locations):
        locations.insert(0, current_location)

    labels = _weather_location_labels(locations)
    return {
        label: location
        for label, location in zip(labels, locations, strict=False)
    }


def _weather_location_labels(locations: list[dict[str, Any]]) -> list[str]:
    base_labels = [_base_weather_location_label(location) for location in locations]
    duplicate_labels = {
        label for label in base_labels if base_labels.count(label) > 1
    }
    labels: list[str] = []
    used_labels: set[str] = set()

    for location, base_label in zip(locations, base_labels, strict=False):
        label = base_label
        if label in duplicate_labels:
            country = str(location.get("Country") or "").strip()
            if country:
                label = f"{base_label}, {country}"
        if label in used_labels:
            location_id = str(location.get("LocationId") or "").strip()
            if location_id:
                label = f"{label} ({location_id})"
        if label in used_labels:
            label = f"{label} #{len(used_labels) + 1}"
        labels.append(label)
        used_labels.add(label)
    return labels


def _base_weather_location_label(location: dict[str, Any]) -> str:
    name = weather_location_name(location)
    country = str(location.get("Country") or "").strip()
    if name:
        return f"{name}, {country}" if country else name
    location_id = str(location.get("LocationId") or "").strip()
    if location_id:
        return location_id
    return "Unknown location"


def _option_for_location(
    location: dict[str, Any] | None,
    locations_by_option: dict[str, dict[str, Any]],
) -> str | None:
    if location is None:
        return None
    location_id = _location_identifier(location)
    for option, candidate in locations_by_option.items():
        if _location_identifier(candidate) == location_id:
            return option
    return _base_weather_location_label(location)


def _location_in_list(
    location: dict[str, Any],
    locations: list[dict[str, Any]],
) -> bool:
    location_id = _location_identifier(location)
    return any(_location_identifier(candidate) == location_id for candidate in locations)


def _location_identifier(location: dict[str, Any]) -> str | None:
    location_id = location.get("LocationId")
    if location_id not in (None, ""):
        return str(location_id)
    country_id = location.get("CountryId")
    name = weather_location_name(location)
    if name and country_id not in (None, ""):
        return f"{country_id}:{name}"
    return name
