"""Radio command helpers for the DHE client."""

from __future__ import annotations

import contextlib
from typing import Any

from .client_command_context import command_context as _command_context
from .client_mapping import (
    radio_station_in_list as _radio_station_in_list,
    radio_station_input_id as _radio_station_input_id,
)
from .client_types import DHEError, DHESession
from .client_value_helpers import clamp as _clamp
from .flow_helpers import (
    request_generation_and_wait as _request_generation_and_wait,
    wait_for_or_refresh as _wait_for_or_refresh,
)
from .protocol import (
    RADIO_ASSIGN_COMMANDS,
    RADIO_CATALOG_GET_COMMANDS,
    RADIO_FAVORITES_GET_COMMAND,
    RADIO_FAVORITE_ASSIGN_COMMAND,
    RADIO_PATH,
    RADIO_STATIONS_GET_COMMAND,
    RADIO_STATION_ASSIGN_COMMAND,
    RADIO_STATION_SEARCH_FIELDS,
)


class DHEClientRadioCommandsMixin:
    """Radio search, favorite and playback write helpers."""

    async def set_radio_play(self, play: bool) -> bool:
        requested = bool(play)
        await self._assign_radio_value("play", requested)
        _command_context(self)._handle_radio_value(f"assign:{RADIO_PATH}:play", requested)
        return requested

    async def set_radio_volume(self, volume_level: float) -> float:
        volume = round(_clamp(float(volume_level), 0.0, 1.0) * 100.0)
        await self._assign_radio_value("volume", volume)
        _command_context(self)._handle_radio_value(f"assign:{RADIO_PATH}:volume", volume)
        return volume / 100.0

    async def start_bluetooth_pairing(self) -> bool:
        """Send the DHE Bluetooth pairing start action."""
        await self._set_bluetooth_pairing(True)
        return True

    async def disconnect_bluetooth_pairing(self) -> bool:
        """Send the DHE Bluetooth pairing disconnect action."""
        await self._set_bluetooth_pairing(False)
        return True

    async def _set_bluetooth_pairing(self, paired: bool) -> None:
        await self._assign_radio_value("paired", paired)
        _command_context(self)._handle_radio_value(f"assign:{RADIO_PATH}:paired", paired)

    async def list_radio_genres(self) -> list[str]:
        """Return the DHE radio genre catalog."""
        return await self.list_radio_catalog("genre")

    async def list_radio_catalog(self, attribute: str) -> list[str]:
        """Return a DHE radio station search catalog."""
        requested_attribute = str(attribute).strip().lower()
        command = RADIO_CATALOG_GET_COMMANDS.get(requested_attribute)
        if command is None:
            raise DHEError(f"Unsupported DHE radio catalog: {attribute}")
        client = _command_context(self)

        async def _operation(ctx: DHESession) -> list[str]:
            generation = client._radio_catalog_generations[requested_attribute]
            await client._request_app_value(ctx, command)
            return await client._wait_for_radio_catalog(
                requested_attribute,
                generation,
            )

        return await client._run_command_with_reconnect_retry(
            f"Could not read DHE radio {requested_attribute} catalog",
            _operation,
        )

    async def search_radio_stations_by_genre(self, genre: str) -> list[dict[str, Any]]:
        """Search radio stations by DHE radio genre path."""
        return await self.search_radio_stations("genre", genre)

    async def search_radio_stations(
        self,
        attribute: str,
        value: str,
        *,
        search_text: str | None = None,
    ) -> list[dict[str, Any]]:
        requested_attribute = str(attribute).strip().lower()
        requested_value = str(value).strip()
        requested_search_text = (
            str(search_text).strip() if search_text is not None else ""
        )
        if requested_attribute not in RADIO_STATION_SEARCH_FIELDS:
            raise DHEError(f"Unsupported DHE radio station search: {attribute}")
        if not requested_value:
            raise DHEError("Radio station search value must not be empty")
        if search_text is not None and not requested_search_text:
            raise DHEError("Radio station search text must not be empty")
        search_payload = {
            "attribute": requested_attribute,
            "value": requested_value,
        }
        if requested_search_text:
            search_payload["text"] = requested_search_text
        client = _command_context(self)

        async def _operation(ctx: DHESession) -> list[dict[str, Any]]:
            generation = client._radio_stations_generation
            await client._post_packet(ctx, client._message_packet({
                "command": RADIO_STATIONS_GET_COMMAND,
                "value": search_payload,
            }))
            return await client._wait_for_radio_stations(generation)

        return await client._run_command_with_reconnect_retry(
            "Could not search DHE radio stations",
            _operation,
        )

    async def list_radio_favorites(self) -> list[dict[str, Any]]:
        """Return DHE radio favorites."""
        client = _command_context(self)

        async def _operation(ctx: DHESession) -> list[dict[str, Any]]:
            return await self._request_radio_favorites(ctx)

        return await client._run_command_with_reconnect_retry(
            "Could not read DHE radio favorites",
            _operation,
        )

    def _require_radio_station_id(self, station: dict[str, Any] | int | str) -> int:
        station_id = _radio_station_input_id(station)
        if station_id is None:
            raise DHEError("Radio station must include Id")
        return station_id

    async def _request_radio_favorites(self, ctx: DHESession) -> list[dict[str, Any]]:
        client = _command_context(self)
        return await _request_generation_and_wait(
            lambda: client._request_app_value(ctx, RADIO_FAVORITES_GET_COMMAND),
            lambda: client._radio_favorites_generation,
            client._wait_for_radio_favorites,
        )

    async def _assign_radio_favorite_and_wait(
        self,
        ctx: DHESession,
        station_id: int,
    ) -> list[dict[str, Any]]:
        client = _command_context(self)
        generation = client._radio_favorites_generation
        await client._send_ste_command(ctx, RADIO_FAVORITE_ASSIGN_COMMAND, station_id)
        return await _wait_for_or_refresh(
            lambda: client._wait_for_radio_favorites(generation),
            lambda: client._request_app_value(ctx, RADIO_FAVORITES_GET_COMMAND),
            retry_exceptions=(DHEError,),
        )

    async def add_radio_favorite(
        self,
        station: dict[str, Any] | int | str,
        *,
        select: bool = True,
    ) -> bool:
        """Add a radio station favorite and optionally select it."""
        station_id = self._require_radio_station_id(station)
        client = _command_context(self)

        async def _operation(ctx: DHESession) -> bool:
            favorites = client._radio_favorites()
            is_favorite = _radio_station_in_list(station_id, favorites)
            try:
                favorites = await self._request_radio_favorites(ctx)
                is_favorite = _radio_station_in_list(station_id, favorites)
            except DHEError as err:
                if not is_favorite:
                    raise DHEError(
                        "Cannot safely add DHE radio favorite without a fresh favorite list"
                    ) from err

            if not is_favorite:
                favorites = await self._assign_radio_favorite_and_wait(ctx, station_id)
                is_favorite = _radio_station_in_list(station_id, favorites)
                if not is_favorite:
                    raise DHEError(f"DHE radio favorite {station_id} did not change")

            if select:
                await client._send_ste_command(
                    ctx,
                    RADIO_STATION_ASSIGN_COMMAND,
                    station_id,
                )
                with contextlib.suppress(DHEError):
                    await client._wait_for_radio_station(station_id)
            return True

        return await client._run_command_with_reconnect_retry(
            "Could not add DHE radio favorite",
            _operation,
        )

    async def remove_radio_favorite(self, station: dict[str, Any] | int | str) -> bool:
        """Remove a radio station favorite."""
        station_id = self._require_radio_station_id(station)
        client = _command_context(self)

        async def _operation(ctx: DHESession) -> bool:
            favorites = await self._request_radio_favorites(ctx)
            is_favorite = _radio_station_in_list(station_id, favorites)
            if not is_favorite:
                return True

            favorites = await self._assign_radio_favorite_and_wait(ctx, station_id)
            is_favorite = _radio_station_in_list(station_id, favorites)
            if is_favorite:
                raise DHEError("DHE radio favorite did not change")
            return True

        return await client._run_command_with_reconnect_retry(
            "Could not remove DHE radio favorite",
            _operation,
        )

    async def select_radio_station(self, station: dict[str, Any] | int | str) -> bool:
        """Select/play a radio station by station payload or station ID."""
        station_id = self._require_radio_station_id(station)
        client = _command_context(self)

        async def _operation(ctx: DHESession) -> bool:
            await client._send_ste_command(ctx, RADIO_STATION_ASSIGN_COMMAND, station_id)
            with contextlib.suppress(DHEError):
                await client._wait_for_radio_station(station_id)
            return True

        return await client._run_command_with_reconnect_retry(
            "Could not select DHE radio station",
            _operation,
        )

    async def _assign_radio_value(self, field: str, value: Any) -> None:
        command = f"assign:{RADIO_PATH}:{field}"
        if command not in RADIO_ASSIGN_COMMANDS:
            raise DHEError(f"Unsupported DHE radio assignment: {field}")
        client = _command_context(self)

        async def _operation(ctx: DHESession) -> None:
            await client._send_ste_command(ctx, command, value)

        await client._run_command_with_reconnect_retry(
            f"Could not write DHE radio {field}",
            _operation,
        )
