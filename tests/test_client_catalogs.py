"""Focused DHE client regression tests."""

from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import AsyncMock

from tests.client_test_support import (
    PACKAGE_NAME,
    _load_client,
    _load_protocol,
)


class TestClientCatalogs(unittest.IsolatedAsyncioTestCase):
    async def test_toggle_weather_favorite_does_not_retry(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError
        client = DHEClient.__new__(DHEClient)
        location = {"LocationId": "ID=1", "Name": "Essen"}

        client._command_lock = asyncio.Lock()
        client._ctx = object()
        client._ensure_ready = AsyncMock()
        client._assign_weather_favorite_and_wait = AsyncMock(
            side_effect=DHEError("confirmation timeout")
        )

        with self.assertRaisesRegex(
            DHEError,
            "Could not toggle DHE weather favorite: confirmation timeout",
        ):
            await DHEClient.toggle_weather_favorite(client, location)

        client._ensure_ready.assert_awaited_once()
        client._assign_weather_favorite_and_wait.assert_awaited_once_with(
            client._ctx,
            location,
        )


    async def test_add_weather_favorite_existing_and_refresh_timeout_no_toggle(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError
        client = DHEClient.__new__(DHEClient)
        location = {"LocationId": "ID=1", "Name": "Essen"}

        client._last_weather_state = {
            "favorites": [location],
        }
        client._weather_favorites = lambda: [location]
        client._request_weather_favorites = AsyncMock(side_effect=DHEError("timeout"))
        client._assign_weather_favorite_and_wait = AsyncMock(
            side_effect=AssertionError("must not toggle existing favorite")
        )
        client._send_ste_command = AsyncMock()
        client._wait_for_weather_location = AsyncMock()

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry

        result = await DHEClient.add_weather_favorite(client, location)

        self.assertTrue(result)
        client._request_weather_favorites.assert_awaited_once()
        client._assign_weather_favorite_and_wait.assert_not_awaited()
        client._send_ste_command.assert_not_awaited()
        client._wait_for_weather_location.assert_not_awaited()


    async def test_add_weather_favorite_missing_in_stale_cache_fails_safely(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError
        client = DHEClient.__new__(DHEClient)
        location = {"LocationId": "ID=2", "Name": "Stuttgart"}
        cached_location = {"LocationId": "ID=1", "Name": "Essen"}

        client._last_weather_state = {
            "favorites": [cached_location],
        }
        client._weather_favorites = lambda: [cached_location]
        client._request_weather_favorites = AsyncMock(side_effect=DHEError("timeout"))
        client._assign_weather_favorite_and_wait = AsyncMock(
            side_effect=AssertionError("must not toggle when cache is stale")
        )
        client._send_ste_command = AsyncMock()
        client._wait_for_weather_location = AsyncMock()

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry

        with self.assertRaisesRegex(
            DHEError,
            "Cannot safely add DHE weather favorite without a fresh favorite list",
        ):
            await DHEClient.add_weather_favorite(client, location)

        client._request_weather_favorites.assert_awaited_once()
        client._assign_weather_favorite_and_wait.assert_not_awaited()
        client._send_ste_command.assert_not_awaited()
        client._wait_for_weather_location.assert_not_awaited()


    async def test_add_radio_favorite_existing_and_refresh_timeout_no_toggle(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError
        client = DHEClient.__new__(DHEClient)

        station = {"Id": 42, "Name": "WDR 2"}
        client._radio_favorites = lambda: [station]
        client._request_radio_favorites = AsyncMock(side_effect=DHEError("timeout"))
        client._assign_radio_favorite_and_wait = AsyncMock(
            side_effect=AssertionError("must not toggle existing favorite")
        )
        client._send_ste_command = AsyncMock()
        client._wait_for_radio_station = AsyncMock()

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry

        result = await DHEClient.add_radio_favorite(
            client,
            station,
            select=False,
        )

        self.assertTrue(result)
        client._request_radio_favorites.assert_awaited_once()
        client._assign_radio_favorite_and_wait.assert_not_awaited()
        client._send_ste_command.assert_not_awaited()


    async def test_add_radio_favorite_missing_in_stale_cache_fails_safely(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError
        client = DHEClient.__new__(DHEClient)

        station = {"Id": 42, "Name": "WDR 2"}
        cached_station = {"Id": 7, "Name": "NDR"}
        client._radio_favorites = lambda: [cached_station]
        client._request_radio_favorites = AsyncMock(side_effect=DHEError("timeout"))
        client._assign_radio_favorite_and_wait = AsyncMock(
            side_effect=AssertionError("must not toggle unknown station")
        )
        client._send_ste_command = AsyncMock()
        client._wait_for_radio_station = AsyncMock()

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry

        with self.assertRaisesRegex(
            DHEError,
            "Cannot safely add DHE radio favorite without a fresh favorite list",
        ):
            await DHEClient.add_radio_favorite(
                client,
                station,
                select=False,
            )

        client._request_radio_favorites.assert_awaited_once()
        client._assign_radio_favorite_and_wait.assert_not_awaited()
        client._send_ste_command.assert_not_awaited()


    async def test_remove_weather_favorite_existing_and_refresh_timeout_no_toggle(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError
        client = DHEClient.__new__(DHEClient)
        location = {"LocationId": "ID=1", "Name": "Essen"}

        client._last_weather_state = {
            "favorites": [location],
        }
        client._weather_favorites = lambda: [location]
        client._request_weather_favorites = AsyncMock(side_effect=DHEError("timeout"))
        client._assign_weather_favorite_and_wait = AsyncMock(
            side_effect=AssertionError("must not toggle existing favorite")
        )

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry

        with self.assertRaisesRegex(
            DHEError,
            "Cannot safely remove DHE weather favorite without a fresh favorite list",
        ):
            await DHEClient.remove_weather_favorite(client, location)

        client._request_weather_favorites.assert_awaited_once()
        client._assign_weather_favorite_and_wait.assert_not_awaited()


    async def test_remove_weather_favorite_missing_in_stale_cache_fails_safely(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError
        client = DHEClient.__new__(DHEClient)
        location = {"LocationId": "ID=2", "Name": "Stuttgart"}
        cached_location = {"LocationId": "ID=1", "Name": "Essen"}

        client._last_weather_state = {
            "favorites": [cached_location],
        }
        client._weather_favorites = lambda: [cached_location]
        client._request_weather_favorites = AsyncMock(side_effect=DHEError("timeout"))
        client._assign_weather_favorite_and_wait = AsyncMock(
            side_effect=AssertionError("must not toggle unknown location")
        )

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry

        with self.assertRaisesRegex(
            DHEError,
            "Cannot safely remove DHE weather favorite without a fresh favorite list",
        ):
            await DHEClient.remove_weather_favorite(client, location)

        client._request_weather_favorites.assert_awaited_once()
        client._assign_weather_favorite_and_wait.assert_not_awaited()


    async def test_runtime_measurement_refresh_tracks_only_radio_app_readbacks(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHESession = client_module.DHESession

        client = DHEClient.__new__(DHEClient)
        ctx = DHESession(url_token="token", sid="sid")
        client._pending_app_read_deadlines = {}
        client._post_packet = AsyncMock()
        client._message_packet = lambda payload: str(payload)

        await DHEClient._request_app_value(
            client,
            ctx,
            "get:ste.app.weather:location",
        )
        await DHEClient._request_app_value(
            client,
            ctx,
            "get:ste.app.radio:station",
        )

        self.assertNotIn(
            "get:ste.app.weather:location",
            client._pending_app_read_deadlines,
        )
        self.assertIn(
            "get:ste.app.radio:station",
            client._pending_app_read_deadlines,
        )


    async def test_runtime_radio_station_readback_does_not_infer_playing(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._last_app_values = {}
        client._last_radio_state = {}
        client._last_radio_favorites = []
        client._radio_favorites_generation = 0
        states: list[dict[str, object]] = []
        client._radio_callbacks = {states.append}

        DHEClient._handle_radio_value(
            client,
            "set:ste.app.radio:station",
            {"Id": 166, "Name": "Radio Test"},
            requested_readback=True,
        )

        self.assertEqual(client._last_radio_state["station"]["Id"], 166)
        self.assertNotIn("play", client._last_radio_state)
        self.assertEqual(states[-1]["station"]["Id"], 166)


    async def test_runtime_radio_device_station_update_does_not_infer_playing(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._last_app_values = {}
        client._last_radio_state = {}
        client._last_radio_favorites = []
        client._radio_favorites_generation = 0
        states: list[dict[str, object]] = []
        client._radio_callbacks = {states.append}

        DHEClient._handle_radio_value(
            client,
            "set:ste.app.radio:station",
            {"Id": 166, "Name": "Radio Test"},
        )

        self.assertNotIn("play", client._last_radio_state)
        self.assertNotIn("play", states[-1])
        self.assertEqual(client._last_radio_state["station"]["Id"], 166)
        self.assertEqual(states[-1]["station"]["Id"], 166)


    async def test_runtime_radio_device_title_update_does_not_infer_playing(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._last_app_values = {}
        client._last_radio_state = {"play": False}
        client._last_radio_favorites = []
        client._radio_favorites_generation = 0
        states: list[dict[str, object]] = []
        client._radio_callbacks = {states.append}

        DHEClient._handle_radio_value(
            client,
            "set:ste.app.radio:title",
            "Now Playing",
        )

        self.assertIs(client._last_radio_state["play"], False)
        self.assertIs(states[-1]["play"], False)
        self.assertEqual(client._last_radio_state["title"], "Now Playing")
        self.assertEqual(states[-1]["title"], "Now Playing")


    async def test_runtime_ignores_unknown_radio_and_bad_weather_payloads(
        self,
    ) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient
        client_types = sys.modules[f"{PACKAGE_NAME}.client_types"]

        client = DHEClient.__new__(DHEClient)
        client._diagnostic_state = {}
        client._diagnostic_callbacks = set()
        client._last_message_monotonic = None
        client._message_count = 0
        client._runtime_parser_stats = {}
        client._last_runtime_parser_category = None
        client._last_app_values = {}
        client._last_radio_state = {}
        client._last_radio_stations = []
        client._last_radio_favorites = []
        client._last_radio_catalogs = {
            field: [] for field in protocol_module.RADIO_CATALOG_FIELDS
        }
        client._last_radio_genres = []
        client._radio_catalog_generations = {
            field: 0 for field in protocol_module.RADIO_CATALOG_FIELDS
        }
        client._radio_stations_generation = 0
        client._radio_favorites_generation = 0
        client._radio_genres_generation = 0
        client._radio_callbacks = set()
        client._last_weather_state = {}
        client._last_weather_countries = []
        client._weather_callbacks = set()
        client._weather_search_generation = 0
        client._weather_favorites_generation = 0
        client._weather_countries_generation = 0

        await DHEClient._handle_runtime_event(
            client,
            client_types.DHEEvent(
                "message",
                {
                    "command": "set:ste.app.radio:unknownRuntimeField",
                    "value": {"unexpected": "shape"},
                },
            ),
        )
        await DHEClient._handle_runtime_event(
            client,
            client_types.DHEEvent(
                "message",
                {
                    "command": protocol_module.WEATHER_FORECAST_SET_COMMAND,
                    "value": "not-a-weather-list",
                },
            ),
        )

        self.assertEqual(client._last_radio_state, {})
        self.assertEqual(client._last_weather_state, {})
        self.assertEqual(client._runtime_parser_stats["radio_unhandled"], 1)
        self.assertEqual(client._runtime_parser_stats["weather_state"], 1)
        self.assertIn(
            protocol_module.WEATHER_FORECAST_SET_COMMAND,
            client._last_app_values,
        )
