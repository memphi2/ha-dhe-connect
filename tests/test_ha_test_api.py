"""Tests for the Home Assistant API test helper."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from scripts import ha_test_api


def _write_auth(config: Path, refresh_tokens) -> None:
    storage = config / ".storage"
    storage.mkdir(parents=True)
    (storage / "auth").write_text(
        json.dumps({"data": {"refresh_tokens": refresh_tokens}}),
        encoding="utf-8",
    )


class TestHATestApi(unittest.TestCase):
    """Validate HA test API helper behavior."""

    def test_cleanup_localhost_tokens_from_list_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config"
            backup_dir = Path(temp_dir) / "backup"
            _write_auth(
                config,
                [
                    {"id": "keep", "client_id": "https://example.invalid/"},
                    {"id": "drop", "client_id": "http://localhost/"},
                ],
            )

            result = ha_test_api.cleanup_localhost_refresh_tokens(
                config,
                backup_dir=backup_dir,
            )

            auth = json.loads((config / ".storage" / "auth").read_text())
            self.assertEqual(result.removed, 1)
            self.assertIsNotNone(result.backup_path)
            self.assertEqual(
                auth["data"]["refresh_tokens"],
                [{"id": "keep", "client_id": "https://example.invalid/"}],
            )
            backup = json.loads(result.backup_path.read_text())
            self.assertEqual(len(backup["data"]["refresh_tokens"]), 2)

    def test_cleanup_localhost_tokens_from_dict_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config"
            backup_dir = Path(temp_dir) / "backup"
            _write_auth(
                config,
                {
                    "keep": {"client_id": "https://example.invalid/"},
                    "drop": {"client_id": "http://localhost/"},
                },
            )

            result = ha_test_api.cleanup_localhost_refresh_tokens(
                config,
                backup_dir=backup_dir,
            )

            auth = json.loads((config / ".storage" / "auth").read_text())
            self.assertEqual(result.removed, 1)
            self.assertEqual(
                auth["data"]["refresh_tokens"],
                {"keep": {"client_id": "https://example.invalid/"}},
            )

    def test_cleanup_without_localhost_tokens_does_not_create_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config"
            backup_dir = Path(temp_dir) / "backup"
            _write_auth(config, [{"id": "keep", "client_id": "other"}])

            result = ha_test_api.cleanup_localhost_refresh_tokens(
                config,
                backup_dir=backup_dir,
            )

            self.assertEqual(result.removed, 0)
            self.assertIsNone(result.backup_path)
            self.assertFalse(backup_dir.exists())

    def test_service_smoke_reports_successful_climate_and_radio_actions(self) -> None:
        api = _FakeServiceApi(
            [
                {"state": "heat", "attributes": {"temperature": 42.0}},
                {"state": "off", "attributes": {}},
                {"state": "heat", "attributes": {}},
                {
                    "state": "idle",
                    "attributes": {"source": "A", "source_list": ["A", "B"]},
                },
                {"state": "playing", "attributes": {"source": "B"}},
            ]
        )

        with patch.object(ha_test_api.time, "sleep"):
            results = ha_test_api.run_service_smoke(
                api,
                "access",
                climate_entity="climate.dhe",
                radio_entity="media_player.radio",
            )

        self.assertTrue(all(result.ok for result in results))
        self.assertEqual(
            api.calls,
            [
                ("climate", "turn_off", {"entity_id": "climate.dhe"}),
                ("climate", "turn_on", {"entity_id": "climate.dhe"}),
                ("media_player", "turn_off", {"entity_id": "media_player.radio"}),
                (
                    "media_player",
                    "select_source",
                    {"entity_id": "media_player.radio", "source": "B"},
                ),
            ],
        )

    def test_service_smoke_fails_when_radio_source_does_not_change(self) -> None:
        api = _FakeServiceApi(
            [
                {"state": "heat", "attributes": {"temperature": 42.0}},
                {"state": "off", "attributes": {}},
                {"state": "heat", "attributes": {}},
                {
                    "state": "idle",
                    "attributes": {"source": "A", "source_list": ["A", "B"]},
                },
                {"state": "idle", "attributes": {"source": "A"}},
            ]
        )

        with patch.object(ha_test_api.time, "sleep"):
            results = ha_test_api.run_service_smoke(
                api,
                "access",
                climate_entity="climate.dhe",
                radio_entity="media_player.radio",
            )

        self.assertFalse(results[-1].ok)
        self.assertIn("selected='B'", results[-1].message)

    def test_wait_online_returns_immediately_without_restart_stability(self) -> None:
        api = ha_test_api.HomeAssistantApi("http://ha.test")

        with (
            patch.object(ha_test_api.urllib.request, "urlopen", return_value=_FakeResponse()),
            patch.object(ha_test_api.time, "monotonic", return_value=0.0),
        ):
            result = api.wait_online(require_seen_down=False)

        self.assertTrue(result)

    def test_wait_online_requires_stable_online_window_after_restart(self) -> None:
        api = ha_test_api.HomeAssistantApi("http://ha.test")
        responses = [
            urllib.error.URLError("down"),
            _FakeResponse(),
            _FakeResponse(),
            _FakeResponse(),
        ]

        with (
            patch.object(
                ha_test_api.urllib.request,
                "urlopen",
                side_effect=responses,
            ) as urlopen,
            patch.object(
                ha_test_api.time,
                "monotonic",
                side_effect=[0.0, 1.0, 5.0, 5.0, 24.0, 24.0, 26.0, 26.0],
            ),
            patch.object(ha_test_api.time, "sleep"),
        ):
            result = api.wait_online(
                require_seen_down=True,
                stable_online_seconds=20.0,
                interval=0.0,
            )

        self.assertTrue(result)
        self.assertEqual(urlopen.call_count, 4)

    def test_wait_online_fails_restart_when_no_outage_is_observed(self) -> None:
        api = ha_test_api.HomeAssistantApi("http://ha.test")

        with (
            patch.object(
                ha_test_api.urllib.request,
                "urlopen",
                return_value=_FakeResponse(),
            ) as urlopen,
            patch.object(
                ha_test_api.time,
                "monotonic",
                side_effect=[0.0, 1.0, 10.0, 21.0],
            ),
            patch.object(ha_test_api.time, "sleep"),
        ):
            result = api.wait_online(
                timeout=20.0,
                interval=0.0,
                require_seen_down=True,
                stable_online_seconds=5.0,
            )

        self.assertFalse(result)
        self.assertEqual(urlopen.call_count, 2)

    def test_wait_api_ready_retries_until_stable(self) -> None:
        api = ha_test_api.HomeAssistantApi("http://ha.test")

        with (
            patch.object(
                api,
                "_request_json",
                side_effect=[ConnectionResetError("reset"), (200, {}), (200, {})],
            ) as request_json,
            patch.object(
                ha_test_api.time,
                "monotonic",
                side_effect=[0.0, 1.0, 2.0, 2.0, 8.0, 8.0],
            ),
            patch.object(ha_test_api.time, "sleep"),
        ):
            result = api.wait_api_ready("access", stable_seconds=5.0, interval=0.0)

        self.assertTrue(result)
        self.assertEqual(request_json.call_count, 3)


class _FakeServiceApi:
    def __init__(self, states: list[dict[str, object]]) -> None:
        self._states = states
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def get_state(self, _access_token: str, _entity_id: str) -> dict[str, object]:
        return self._states.pop(0)

    def call_service(
        self,
        _access_token: str,
        domain: str,
        service: str,
        payload: dict[str, object],
    ) -> list[dict[str, object]]:
        self.calls.append((domain, service, payload))
        return [{"entity_id": payload["entity_id"]}]


class _FakeResponse:
    status = 200

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(
        self,
        _exc_type: object,
        _exc: object,
        _traceback: object,
    ) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
