"""Weather command helpers for the DHE client."""

from __future__ import annotations

from typing import Any

from .client_command_context import command_context as _command_context
from .client_mapping import (
    copy_json_like_value as _copy_json_like_value,
    weather_location_has_id as _weather_location_has_id,
    weather_location_id as _weather_location_id,
    weather_location_in_list as _weather_location_in_list,
)
from .client_types import DHEError, DHESession
from .client_value_helpers import raw_to_float as _raw_to_float
from .flow_helpers import (
    request_generation_and_wait as _request_generation_and_wait,
    wait_for_or_refresh as _wait_for_or_refresh,
)
from .protocol import (
    WEATHER_COUNTRIES_GET_COMMAND,
    WEATHER_FAVORITES_GET_COMMAND,
    WEATHER_FAVORITE_ASSIGN_COMMAND,
    WEATHER_FORECAST_GET_COMMAND,
    WEATHER_LOCATION_GET_COMMAND,
)


class DHEClientWeatherCommandsMixin:
    """Weather catalog, favorite and location write helpers."""

    async def search_weather_locations(
        self,
        name: str,
        country_id: int | float | str,
    ) -> list[dict[str, Any]]:
        requested_name = str(name).strip()
        if not requested_name:
            raise DHEError("Weather location search name must not be empty")
        requested_country_id = int(_raw_to_float(country_id))
        client = _command_context(self)

        async def _operation(ctx: DHESession) -> list[dict[str, Any]]:
            generation = client._weather_search_generation
            await client._post_packet(ctx, client._message_packet({
                "command": WEATHER_FORECAST_GET_COMMAND,
                "value": {
                    "name": requested_name,
                    "countryId": requested_country_id,
                },
            }))
            return await client._wait_for_weather_search_results(generation)

        return await client._run_command_with_reconnect_retry(
            "Could not search DHE weather locations",
            _operation,
        )

    async def list_weather_countries(self) -> list[dict[str, Any]]:
        """Return the weather country catalog from the DHE."""
        client = _command_context(self)

        async def _operation(ctx: DHESession) -> list[dict[str, Any]]:
            generation = client._weather_countries_generation
            await client._request_app_value(ctx, WEATHER_COUNTRIES_GET_COMMAND)
            return await client._wait_for_weather_countries(generation)

        return await client._run_command_with_reconnect_retry(
            "Could not read DHE weather countries",
            _operation,
        )

    async def toggle_weather_favorite(self, location: dict[str, Any]) -> bool:
        if not _weather_location_has_id(location):
            raise DHEError("Weather favorite location must include LocationId")
        client = _command_context(self)

        async def _operation(ctx: DHESession) -> bool:
            payload = _copy_json_like_value(location)
            await self._assign_weather_favorite_and_wait(ctx, payload)
            return True

        return await client._run_command_without_reconnect_retry(
            "Could not toggle DHE weather favorite",
            _operation,
        )

    async def list_weather_favorites(self) -> list[dict[str, Any]]:
        """Return the weather favorites from the DHE."""
        client = _command_context(self)

        async def _operation(ctx: DHESession) -> list[dict[str, Any]]:
            return await self._request_weather_favorites(ctx)

        return await client._run_command_with_reconnect_retry(
            "Could not read DHE weather favorites",
            _operation,
        )

    async def add_weather_favorite(self, location: dict[str, Any]) -> bool:
        """Add a weather favorite without toggling an existing favorite off."""
        if not _weather_location_has_id(location):
            raise DHEError("Weather favorite location must include LocationId")
        client = _command_context(self)

        async def _operation(ctx: DHESession) -> bool:
            payload = _copy_json_like_value(location)

            favorites = client._weather_favorites()
            is_favorite = _weather_location_in_list(payload, favorites)
            try:
                favorites = await self._request_weather_favorites(ctx)
                is_favorite = _weather_location_in_list(payload, favorites)
            except DHEError as err:
                if is_favorite:
                    return True

                raise DHEError(
                    "Cannot safely add DHE weather favorite without a fresh favorite list"
                ) from err
            if is_favorite:
                return True

            location_id = _weather_location_id(payload)
            favorites = await self._assign_weather_favorite_and_wait(ctx, payload)
            is_favorite = _weather_location_in_list(payload, favorites)
            if not is_favorite:
                raise DHEError("DHE weather favorite did not change")
            await client._send_ste_command(ctx, WEATHER_LOCATION_GET_COMMAND, location_id)
            await client._wait_for_weather_location(location_id)
            return True

        return await client._run_command_with_reconnect_retry(
            "Could not add DHE weather favorite",
            _operation,
        )

    async def remove_weather_favorite(self, location: dict[str, Any]) -> bool:
        """Remove a weather favorite without toggling a missing favorite on."""
        if not _weather_location_has_id(location):
            raise DHEError("Weather favorite location must include LocationId")
        client = _command_context(self)

        async def _operation(ctx: DHESession) -> bool:
            payload = _copy_json_like_value(location)
            favorites = client._weather_favorites()
            try:
                favorites = await self._request_weather_favorites(ctx)
            except DHEError as err:
                raise DHEError(
                    "Cannot safely remove DHE weather favorite without a fresh "
                    "favorite list"
                ) from err

            is_favorite = _weather_location_in_list(payload, favorites)
            if not is_favorite:
                return True

            favorites = await self._assign_weather_favorite_and_wait(ctx, payload)
            is_favorite = _weather_location_in_list(payload, favorites)
            if is_favorite:
                raise DHEError("DHE weather favorite did not change")
            return True

        return await client._run_command_with_reconnect_retry(
            "Could not remove DHE weather favorite",
            _operation,
        )

    async def select_weather_location(self, location: dict[str, Any] | str) -> bool:
        if isinstance(location, dict):
            location_id = location.get("LocationId")
        else:
            location_id = location
        requested_location_id = str(location_id or "").strip()
        if not requested_location_id:
            raise DHEError("Weather location must include LocationId")
        client = _command_context(self)

        async def _operation(ctx: DHESession) -> bool:
            await client._send_ste_command(
                ctx,
                WEATHER_LOCATION_GET_COMMAND,
                requested_location_id,
            )
            await client._wait_for_weather_location(requested_location_id)
            return True

        return await client._run_command_with_reconnect_retry(
            "Could not select DHE weather location",
            _operation,
        )

    async def _request_weather_favorites(self, ctx: DHESession) -> list[dict[str, Any]]:
        client = _command_context(self)
        return await _request_generation_and_wait(
            lambda: client._request_app_value(ctx, WEATHER_FAVORITES_GET_COMMAND),
            lambda: client._weather_favorites_generation,
            client._wait_for_weather_favorites,
        )

    async def _assign_weather_favorite_and_wait(
        self,
        ctx: DHESession,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        client = _command_context(self)
        generation = client._weather_favorites_generation
        await client._send_ste_command(ctx, WEATHER_FAVORITE_ASSIGN_COMMAND, payload)
        return await _wait_for_or_refresh(
            lambda: client._wait_for_weather_favorites(generation),
            lambda: client._request_app_value(ctx, WEATHER_FAVORITES_GET_COMMAND),
            retry_exceptions=(DHEError,),
        )
