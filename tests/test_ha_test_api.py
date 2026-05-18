"""Tests for the Home Assistant API test helper."""

from __future__ import annotations

from datetime import datetime
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
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

    def test_cleanup_backups_use_microsecond_precision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config"
            backup_dir = Path(temp_dir) / "backup"
            _write_auth(config, [{"id": "drop", "client_id": "http://localhost/"}])

            with patch.object(ha_test_api, "datetime") as datetime_mock:
                datetime_mock.now.side_effect = [
                    datetime(2026, 5, 18, 7, 0, 0, 111111),
                    datetime(2026, 5, 18, 7, 0, 0, 222222),
                ]
                first = ha_test_api.cleanup_localhost_refresh_tokens(
                    config,
                    backup_dir=backup_dir,
                )
                (config / ".storage" / "auth").write_text(
                    json.dumps(
                        {
                            "data": {
                                "refresh_tokens": [
                                    {
                                        "id": "drop",
                                        "client_id": "http://localhost/",
                                    }
                                ]
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                second = ha_test_api.cleanup_localhost_refresh_tokens(
                    config,
                    backup_dir=backup_dir,
                )

            self.assertIsNotNone(first.backup_path)
            self.assertIsNotNone(second.backup_path)
            self.assertNotEqual(first.backup_path, second.backup_path)
            self.assertTrue(first.backup_path.exists())
            self.assertTrue(second.backup_path.exists())

    def test_cleanup_retry_repeats_until_auth_file_stays_clean(self) -> None:
        backup_path = Path("/tmp/auth-backup.json")
        results = [
            ha_test_api.TokenCleanupResult(removed=70, backup_path=backup_path),
            ha_test_api.TokenCleanupResult(removed=1, backup_path=Path("/tmp/again.json")),
            ha_test_api.TokenCleanupResult(removed=0, backup_path=None),
        ]

        with (
            patch.object(
                ha_test_api,
                "cleanup_localhost_refresh_tokens",
                side_effect=results,
            ) as cleanup,
            patch.object(ha_test_api.time, "sleep") as sleep,
        ):
            result = ha_test_api.cleanup_localhost_refresh_tokens_with_retry(
                Path("/config"),
                attempts=5,
                interval=0.5,
            )

        self.assertEqual(result.removed, 71)
        self.assertEqual(result.backup_path, backup_path)
        self.assertEqual(cleanup.call_count, 3)
        sleep.assert_any_call(0.5)
        self.assertEqual(sleep.call_count, 2)

    def test_cleanup_retry_reports_unstable_when_attempts_are_exhausted(self) -> None:
        backup_path = Path("/tmp/auth-backup.json")
        results = [
            ha_test_api.TokenCleanupResult(removed=1, backup_path=backup_path),
            ha_test_api.TokenCleanupResult(removed=1, backup_path=Path("/tmp/again.json")),
        ]

        with (
            patch.object(
                ha_test_api,
                "cleanup_localhost_refresh_tokens",
                side_effect=results,
            ),
            patch.object(ha_test_api.time, "sleep") as sleep,
        ):
            result = ha_test_api.cleanup_localhost_refresh_tokens_with_retry(
                Path("/config"),
                attempts=2,
                interval=0.5,
            )

        self.assertEqual(result.removed, 2)
        self.assertEqual(result.backup_path, backup_path)
        self.assertFalse(result.stable)
        sleep.assert_called_once_with(0.5)

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
                {"state": "off", "attributes": {"source": "A"}},
            ]
        )

        with patch.object(ha_test_api.time, "sleep") as sleep:
            results = ha_test_api.run_service_smoke(
                api,
                "access",
                climate_entity="climate.dhe",
                radio_entity="media_player.radio",
        )

        self.assertTrue(all(result.ok for result in results))
        self.assertEqual(results[0].level, "INFO")
        self.assertIn("restore_after_smoke", results[-1].message)
        sleep.assert_any_call(25.0)
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
                (
                    "media_player",
                    "select_source",
                    {"entity_id": "media_player.radio", "source": "A"},
                ),
                ("media_player", "turn_off", {"entity_id": "media_player.radio"}),
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
                {"state": "off", "attributes": {"source": "A"}},
            ]
        )

        with patch.object(ha_test_api.time, "sleep"):
            results = ha_test_api.run_service_smoke(
                api,
                "access",
                climate_entity="climate.dhe",
                radio_entity="media_player.radio",
                radio_auto_off_seconds=5.0,
            )

        self.assertFalse(results[-2].ok)
        self.assertIn("selected='B'", results[-2].message)
        self.assertIn("restore_after_smoke", results[-1].message)
        self.assertEqual(
            api.calls[-1],
            ("media_player", "turn_off", {"entity_id": "media_player.radio"}),
        )

    def test_service_smoke_fails_when_idle_radio_does_not_restore_to_off(self) -> None:
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
        self.assertIn("state='idle'", results[-1].message)

    def test_service_smoke_skips_when_water_is_running(self) -> None:
        api = _FakeServiceApi([], device_status="status_4")

        results = ha_test_api.run_service_smoke(
            api,
            "access",
            climate_entity="climate.dhe",
            radio_entity="media_player.radio",
        )

        self.assertTrue(all(result.ok for result in results))
        self.assertEqual(results[0].level, "INFO")
        self.assertIn("skipped", results[-1].message)
        self.assertEqual(api.calls, [])

    def test_entity_smoke_checks_core_dhe_state_shapes(self) -> None:
        api = _FakeStateApi(
            [
                {
                    "entity_id": "climate.dhe",
                    "state": "heat",
                    "attributes": {"temperature": 42.0},
                },
                {
                    "entity_id": "media_player.radio",
                    "state": "off",
                    "attributes": {"source_list": ["A"]},
                },
                {
                    "entity_id": "sensor.connection",
                    "state": "connected",
                    "attributes": {},
                },
                {
                    "entity_id": "sensor.power",
                    "state": "0.0",
                    "attributes": {},
                },
                {
                    "entity_id": "sensor.timer_remaining",
                    "state": "1:00",
                    "attributes": {},
                },
                {
                    "entity_id": "switch.timer",
                    "state": "off",
                    "attributes": {},
                },
                {
                    "entity_id": "number.duration",
                    "state": "60",
                    "attributes": {},
                },
            ]
        )

        results = ha_test_api.run_entity_smoke(
            api,
            "access",
            entity_ids=(
                "climate.dhe",
                "media_player.radio",
                "sensor.connection",
                "sensor.power",
                "sensor.timer_remaining",
                "switch.timer",
                "number.duration",
            ),
        )

        self.assertTrue(all(result.ok for result in results))
        self.assertEqual(results[0].level, "INFO")

    def test_entity_smoke_reports_missing_or_bad_entities(self) -> None:
        api = _FakeStateApi(
            [
                {
                    "entity_id": "sensor.connection",
                    "state": "unknown",
                    "attributes": {},
                },
            ]
        )

        results = ha_test_api.run_entity_smoke(
            api,
            "access",
            entity_ids=("sensor.connection", "sensor.missing"),
        )

        self.assertEqual(results[0].level, "INFO")
        self.assertFalse(results[1].ok)
        self.assertIn("unknown", results[1].message)
        self.assertFalse(results[-1].ok)
        self.assertIn("missing", results[-1].message)

    def test_entity_smoke_skips_missing_disabled_registry_entities(self) -> None:
        api = _FakeStateApi([])

        results = ha_test_api.run_entity_smoke(
            api,
            "access",
            entity_ids=("sensor.disabled", "sensor.missing"),
            disabled_entity_ids={"sensor.disabled"},
        )

        self.assertTrue(results[1].ok)
        self.assertIn("skipped disabled", results[1].message)
        self.assertFalse(results[2].ok)
        self.assertIn("missing", results[2].message)

    def test_disabled_entity_ids_from_registry_reads_disabled_entities(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config"
            storage = config / ".storage"
            storage.mkdir(parents=True)
            (storage / "core.entity_registry").write_text(
                json.dumps(
                    {
                        "data": {
                            "entities": [
                                {
                                    "entity_id": "sensor.disabled",
                                    "disabled_by": "integration",
                                },
                                {"entity_id": "sensor.user_disabled", "disabled_by": "user"},
                                {
                                    "entity_id": "sensor.config_disabled",
                                    "disabled_by": "config_entry",
                                },
                                {"entity_id": "sensor.enabled", "disabled_by": None},
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            disabled = ha_test_api.disabled_entity_ids_from_registry(config)

        self.assertEqual(disabled, {"sensor.disabled"})

    def test_default_service_smoke_entities_match_current_registry_names(self) -> None:
        self.assertEqual(
            ha_test_api.DEFAULT_CLIMATE_ENTITY,
            "climate.dhe_connect_water_heating",
        )
        self.assertEqual(
            ha_test_api.DEFAULT_RADIO_ENTITY,
            "media_player.dhe_connect_radio",
        )
        self.assertEqual(
            ha_test_api.DEFAULT_TIMER_REMAINING_ENTITY,
            "sensor.dhe_connect_brush_timer_remaining",
        )

    def test_timer_state_seconds_parses_home_assistant_timer_text(self) -> None:
        self.assertEqual(ha_test_api._timer_state_seconds("1:05"), 65)
        self.assertEqual(ha_test_api._timer_state_seconds("0:00"), 0)
        self.assertIsNone(ha_test_api._timer_state_seconds("unknown"))
        self.assertIsNone(ha_test_api._timer_state_seconds("1:99"))

    def test_timer_smoke_skips_when_water_is_running(self) -> None:
        api = _FakeServiceApi(
            [
                {"state": "180", "attributes": {}},
            ],
            device_status="status_2",
        )

        results = ha_test_api.run_timer_smoke(
            api,
            "access",
            switch_entity="switch.timer",
            remaining_entity="sensor.timer_remaining",
            duration_entity="number.duration",
        )

        self.assertTrue(all(result.ok for result in results))
        self.assertEqual(results[0].level, "INFO")
        self.assertIn("skipped", results[-1].message)
        self.assertEqual(api.calls, [])

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

    def test_main_waits_for_auth_providers_before_login(self) -> None:
        class _Api:
            def __init__(self, _url: str) -> None:
                pass

            def wait_online(self, **_kwargs) -> bool:
                return False

            def login(self, *_args):
                raise AssertionError("login should not run before HA is reachable")

        with (
            patch.object(ha_test_api, "HomeAssistantApi", _Api),
            patch.dict(os.environ, {"HA_TEST_PASSWORD": "secret"}),
            patch.object(
                sys,
                "argv",
                [
                    "ha_test_api.py",
                    "--username",
                    "test-user",
                    "--login-wait-timeout",
                    "0.1",
                    "--login-wait-interval",
                    "0",
                ],
            ),
        ):
            result = ha_test_api.main()

        self.assertEqual(result, 1)

    def test_main_redacts_login_error_context(self) -> None:
        class _Api:
            def __init__(self, _url: str) -> None:
                pass

            def wait_online(self, **_kwargs) -> bool:
                return True

            def login(self, *_args):
                private_host = ".".join(("172", "16", "1", "147"))
                raise RuntimeError(
                    "auth failed access_token=abc123 refresh_token='def456' "
                    f"password=secret http://user:secret@{private_host}:8123"
                )

        output = io.StringIO()
        with (
            patch.object(ha_test_api, "HomeAssistantApi", _Api),
            patch.dict(os.environ, {"HA_TEST_PASSWORD": "secret"}),
            patch.object(
                sys,
                "argv",
                ["ha_test_api.py", "--username", "test-user"],
            ),
            redirect_stdout(output),
        ):
            result = ha_test_api.main()

        text = output.getvalue()
        self.assertEqual(result, 1)
        self.assertIn("FAIL: HA auth login failed", text)
        self.assertIn("<redacted>", text)
        self.assertIn("<private-host>", text)
        self.assertNotIn("abc123", text)
        self.assertNotIn("def456", text)
        self.assertNotIn("secret", text)
        self.assertNotIn(".".join(("172", "16", "1", "147")), text)

    def test_main_still_cleans_tokens_when_pre_cleanup_restart_fails(self) -> None:
        class _Api:
            def __init__(self, _url: str) -> None:
                pass

            def wait_online(self, **_kwargs) -> bool:
                return True

            def login(self, *_args):
                return ha_test_api.AuthToken("access", "refresh")

            def revoke_refresh_token(self, _refresh_token: str) -> bool:
                raise RuntimeError("revoke failed")

            def restart(self, *_args, **_kwargs) -> str:
                raise RuntimeError("restart failed")

        output = io.StringIO()
        with (
            patch.object(ha_test_api, "HomeAssistantApi", _Api),
            patch.object(
                ha_test_api,
                "cleanup_localhost_refresh_tokens_with_retry",
                return_value=ha_test_api.TokenCleanupResult(removed=1, backup_path=None),
            ) as cleanup,
            patch.dict(os.environ, {"HA_TEST_PASSWORD": "secret"}),
            patch.object(
                sys,
                "argv",
                [
                    "ha_test_api.py",
                    "--username",
                    "test-user",
                    "--cleanup-localhost-tokens",
                    "--restart-before-localhost-cleanup",
                ],
            ),
            redirect_stdout(output),
        ):
            result = ha_test_api.main()

        self.assertEqual(result, 0)
        cleanup.assert_called_once()
        text = output.getvalue()
        self.assertIn("WARN: restart before localhost token cleanup failed", text)
        self.assertIn("PASS: localhost token cleanup removed=1", text)

    def test_main_restarts_again_before_cleanup_when_restart_was_requested(self) -> None:
        instances = []

        class _Api:
            def __init__(self, _url: str) -> None:
                self.restart_count = 0
                instances.append(self)

            def wait_online(self, **_kwargs) -> bool:
                return True

            def login(self, *_args):
                return ha_test_api.AuthToken("access", "refresh")

            def restart(self, *_args, **_kwargs) -> str:
                self.restart_count += 1
                return "restart requested"

            def revoke_refresh_token(self, _refresh_token: str) -> bool:
                raise RuntimeError("revoke failed")

        with (
            patch.object(ha_test_api, "HomeAssistantApi", _Api),
            patch.object(
                ha_test_api,
                "cleanup_localhost_refresh_tokens_with_retry",
                return_value=ha_test_api.TokenCleanupResult(removed=1, backup_path=None),
            ),
            patch.dict(os.environ, {"HA_TEST_PASSWORD": "secret"}),
            patch.object(
                sys,
                "argv",
                [
                    "ha_test_api.py",
                    "--username",
                    "test-user",
                    "--restart",
                    "--cleanup-localhost-tokens",
                    "--restart-before-localhost-cleanup",
                ],
            ),
        ):
            result = ha_test_api.main()

        self.assertEqual(result, 0)
        self.assertEqual(instances[0].restart_count, 2)

    def test_main_returns_failure_when_cleanup_does_not_stabilize(self) -> None:
        class _Api:
            def __init__(self, _url: str) -> None:
                pass

            def wait_online(self, **_kwargs) -> bool:
                return True

            def login(self, *_args):
                return ha_test_api.AuthToken("access", "refresh")

            def revoke_refresh_token(self, _refresh_token: str) -> bool:
                raise RuntimeError("revoke failed")

        output = io.StringIO()
        with (
            patch.object(ha_test_api, "HomeAssistantApi", _Api),
            patch.object(
                ha_test_api,
                "cleanup_localhost_refresh_tokens_with_retry",
                return_value=ha_test_api.TokenCleanupResult(
                    removed=2,
                    backup_path=None,
                    stable=False,
                ),
            ),
            patch.dict(os.environ, {"HA_TEST_PASSWORD": "secret"}),
            patch.object(
                sys,
                "argv",
                [
                    "ha_test_api.py",
                    "--username",
                    "test-user",
                    "--cleanup-localhost-tokens",
                ],
            ),
            redirect_stdout(output),
        ):
            result = ha_test_api.main()

        self.assertEqual(result, 3)
        self.assertIn("WARN: localhost token cleanup", output.getvalue())

    def test_parse_args_rejects_negative_cleanup_interval(self) -> None:
        with (
            patch.object(
                sys,
                "argv",
                [
                    "ha_test_api.py",
                    "--cleanup-localhost-token-interval",
                    "-0.1",
                ],
            ),
            self.assertRaises(SystemExit),
        ):
            ha_test_api._parse_args()

    def test_ha_scripts_can_run_directly(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for script in ("ha_test_api.py", "ha_test_smoke.py"):
            with self.subTest(script=script):
                result = subprocess.run(
                    [sys.executable, str(root / "scripts" / script), "--help"],
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assertEqual(result.returncode, 0, result.stderr)


class _FakeServiceApi:
    def __init__(
        self,
        states: list[dict[str, object]],
        *,
        device_status: str = "normal",
    ) -> None:
        self._states = states
        self._device_status = device_status
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def get_state(self, _access_token: str, entity_id: str) -> dict[str, object]:
        if entity_id == "sensor.dhe_connect_device_status":
            return {"entity_id": entity_id, "state": self._device_status}
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


class _FakeStateApi:
    def __init__(self, states: list[dict[str, object]]) -> None:
        self._states = states

    def get_states(self, _access_token: str) -> list[dict[str, object]]:
        return self._states


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
