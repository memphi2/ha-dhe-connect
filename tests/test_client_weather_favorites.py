"""Behavior tests for weather favorites in the DHE client."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_client():
    from custom_components.stiebel_dhe_connect import client as client_module

    return client_module


class TestClientWeatherFavorites(unittest.IsolatedAsyncioTestCase):
    """Validate weather-favorite toggle safeguards."""

    async def test_add_weather_favorite_existing_and_refresh_timeout_no_toggle(self) -> None:
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

    async def test_pairing_notification_ids_include_port(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        client_a = DHEClient.__new__(DHEClient)
        client_a.host = "dhe.local"
        client_a.port = 8443

        client_b = DHEClient.__new__(DHEClient)
        client_b.host = "dhe.local"
        client_b.port = 9443

        self.assertNotEqual(
            client_a._pairing_notification_id,
            client_b._pairing_notification_id,
        )
        self.assertNotEqual(
            client_a._pairing_confirmation_notification_id,
            client_b._pairing_confirmation_notification_id,
        )

    async def test_set_price_rolls_back_when_second_write_fails(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError

        client = DHEClient.__new__(DHEClient)
        euros_id = 100
        cents_id = 101
        client._last_measurements = {
            euros_id: 0.0,
            cents_id: 29.0,
        }

        calls: list[tuple[int, float]] = []

        async def _write_odb_value(odb_id: int, value):
            calls.append((odb_id, float(value)))
            if (odb_id, float(value)) == (cents_id, 5.0):
                raise DHEError("write failed")
            return float(value)

        client.write_odb_value = AsyncMock(side_effect=_write_odb_value)

        with self.assertRaises(DHEError):
            await DHEClient._set_price(
                client,
                1.05,
                euros_id,
                cents_id,
                max_value=9.99,
            )

        self.assertEqual(
            calls,
            [
                (euros_id, 1.0),
                (cents_id, 5.0),
                (euros_id, 0.0),
                (cents_id, 29.0),
            ],
        )


if __name__ == "__main__":
    unittest.main()
