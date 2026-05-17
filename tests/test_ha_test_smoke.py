"""Tests for the Home Assistant test smoke-check script."""

from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import ha_test_smoke  # noqa: E402


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _create_recorder_db(path: Path) -> None:
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(
            """
            CREATE TABLE states_meta (
                metadata_id INTEGER PRIMARY KEY,
                entity_id TEXT NOT NULL
            );
            CREATE TABLE state_attributes (
                attributes_id INTEGER PRIMARY KEY,
                shared_attrs TEXT
            );
            CREATE TABLE states (
                state_id INTEGER PRIMARY KEY,
                metadata_id INTEGER NOT NULL,
                state TEXT NOT NULL,
                attributes_id INTEGER,
                last_updated_ts REAL
            );
            """
        )
        conn.commit()


def _insert_state(
    path: Path,
    *,
    state_id: int,
    metadata_id: int,
    entity_id: str,
    state: str,
    attributes: dict | None = None,
) -> None:
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO states_meta(metadata_id, entity_id) VALUES(?, ?)",
            (metadata_id, entity_id),
        )
        attributes_id = None
        if attributes is not None:
            attributes_id = state_id
            conn.execute(
                """
                INSERT INTO state_attributes(attributes_id, shared_attrs)
                VALUES(?, ?)
                """,
                (attributes_id, json.dumps(attributes)),
            )
        conn.execute(
            """
            INSERT INTO states(
                state_id,
                metadata_id,
                state,
                attributes_id,
                last_updated_ts
            )
            VALUES(?, ?, ?, ?, ?)
            """,
            (state_id, metadata_id, state, attributes_id, float(state_id)),
        )
        conn.commit()


class TestHaTestSmoke(unittest.TestCase):
    """Validate reusable smoke-test helpers against fake HA storage."""

    def test_load_enabled_dhe_entities_from_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir)
            _write_json(
                config / ".storage" / "core.entity_registry",
                {
                    "data": {
                        "entities": [
                            {
                                "entity_id": "climate.dhe_connect",
                                "platform": "stiebel_dhe_connect",
                                "disabled_by": None,
                            },
                            {
                                "entity_id": "sensor.dhe_connect_debug",
                                "platform": "stiebel_dhe_connect",
                                "disabled_by": "integration",
                            },
                            {
                                "entity_id": "sensor.other",
                                "platform": "other",
                            },
                        ]
                    }
                },
            )

            entries = ha_test_smoke.load_entity_registry(config)

            self.assertEqual([entry.entity_id for entry in entries], [
                "climate.dhe_connect",
                "sensor.dhe_connect_debug",
            ])
            self.assertEqual(
                ha_test_smoke.enabled_entity_ids(entries),
                ["climate.dhe_connect"],
            )

    def test_localhost_token_count_supports_dict_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir)
            _write_json(
                config / ".storage" / "auth",
                {
                    "data": {
                        "refresh_tokens": {
                            "one": {"client_id": "http://localhost/"},
                            "two": {"client_id": "https://example.test/"},
                        }
                    }
                },
            )

            self.assertEqual(ha_test_smoke.count_localhost_refresh_tokens(config), 1)

    def test_auth_check_reports_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir)
            auth_path = config / ".storage" / "auth"
            auth_path.parent.mkdir(parents=True, exist_ok=True)
            auth_path.write_text("{", encoding="utf-8")

            result = ha_test_smoke.check_localhost_refresh_tokens(config)

            self.assertFalse(result.ok)
            self.assertIn("auth storage contains invalid JSON", result.message)

    def test_state_health_accepts_connected_core_entities(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "home-assistant_v2.db"
            _create_recorder_db(db_path)
            _insert_state(
                db_path,
                state_id=1,
                metadata_id=1,
                entity_id="climate.dhe_connect",
                state="heat",
                attributes={"connection_state": "connected"},
            )
            _insert_state(
                db_path,
                state_id=2,
                metadata_id=2,
                entity_id="sensor.dhe_connect_verbindungsstatus",
                state="connected",
            )
            _insert_state(
                db_path,
                state_id=3,
                metadata_id=3,
                entity_id="sensor.dhe_connect_reconnects",
                state="0",
            )
            _insert_state(
                db_path,
                state_id=4,
                metadata_id=4,
                entity_id="sensor.dhe_connect_letzter_reconnect_grund",
                state="Kein Reconnect",
            )
            _insert_state(
                db_path,
                state_id=5,
                metadata_id=5,
                entity_id="button.dhe_connect_speicher_1",
                state="unknown",
            )
            entries = [
                ha_test_smoke.EntityRegistryEntry(
                    "climate.dhe_connect",
                    "climate",
                    "stiebel_dhe_connect",
                ),
                ha_test_smoke.EntityRegistryEntry(
                    "sensor.dhe_connect_verbindungsstatus",
                    "sensor",
                    "stiebel_dhe_connect",
                ),
                ha_test_smoke.EntityRegistryEntry(
                    "sensor.dhe_connect_reconnects",
                    "sensor",
                    "stiebel_dhe_connect",
                ),
                ha_test_smoke.EntityRegistryEntry(
                    "sensor.dhe_connect_letzter_reconnect_grund",
                    "sensor",
                    "stiebel_dhe_connect",
                ),
                ha_test_smoke.EntityRegistryEntry(
                    "button.dhe_connect_speicher_1",
                    "button",
                    "stiebel_dhe_connect",
                ),
            ]

            states = ha_test_smoke.load_latest_states(
                db_path,
                ha_test_smoke.enabled_entity_ids(entries),
            )
            results = ha_test_smoke.evaluate_state_health(entries, states)

            self.assertTrue(all(result.ok for result in results), results)

    def test_latest_states_fall_back_to_dhe_connect_recorder_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "home-assistant_v2.db"
            _create_recorder_db(db_path)
            _insert_state(
                db_path,
                state_id=1,
                metadata_id=1,
                entity_id="climate.dhe_connect",
                state="heat",
                attributes={"connection_state": "connected"},
            )
            _insert_state(
                db_path,
                state_id=2,
                metadata_id=2,
                entity_id="sensor.unrelated",
                state="ok",
            )

            states = ha_test_smoke.load_latest_states(db_path, [])

            self.assertEqual(list(states), ["climate.dhe_connect"])

    def test_state_health_skips_disabled_connection_sensor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "home-assistant_v2.db"
            _create_recorder_db(db_path)
            _insert_state(
                db_path,
                state_id=1,
                metadata_id=1,
                entity_id="climate.dhe_connect",
                state="heat",
                attributes={"connection_state": "connected"},
            )
            entries = [
                ha_test_smoke.EntityRegistryEntry(
                    "climate.dhe_connect",
                    "climate",
                    "stiebel_dhe_connect",
                ),
                ha_test_smoke.EntityRegistryEntry(
                    "sensor.dhe_connect_connection_state",
                    "sensor",
                    "stiebel_dhe_connect",
                    disabled_by="integration",
                ),
            ]

            states = ha_test_smoke.load_latest_states(
                db_path,
                ha_test_smoke.enabled_entity_ids(entries),
            )
            results = ha_test_smoke.evaluate_state_health(entries, states)

            self.assertTrue(all(result.ok for result in results), results)
            self.assertIn(
                "connection-state sensor disabled or not present; skipped",
                [result.message for result in results],
            )

    def test_state_health_allows_known_pending_runtime_entities(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "home-assistant_v2.db"
            _create_recorder_db(db_path)
            _insert_state(
                db_path,
                state_id=1,
                metadata_id=1,
                entity_id="climate.dhe_connect",
                state="heat",
                attributes={"connection_state": "connected"},
            )
            _insert_state(
                db_path,
                state_id=2,
                metadata_id=2,
                entity_id="sensor.dhe_connect_heating_energy_total",
                state="unavailable",
            )
            _insert_state(
                db_path,
                state_id=3,
                metadata_id=3,
                entity_id="text.dhe_connect_memory_4_name",
                state="unknown",
            )
            entries = [
                ha_test_smoke.EntityRegistryEntry(
                    "climate.dhe_connect",
                    "climate",
                    "stiebel_dhe_connect",
                ),
                ha_test_smoke.EntityRegistryEntry(
                    "sensor.dhe_connect_heating_energy_total",
                    "sensor",
                    "stiebel_dhe_connect",
                    translation_key="heating_energy_total",
                ),
                ha_test_smoke.EntityRegistryEntry(
                    "text.dhe_connect_memory_4_name",
                    "text",
                    "stiebel_dhe_connect",
                    translation_key="temperature_memory_4_name",
                ),
            ]

            states = ha_test_smoke.load_latest_states(
                db_path,
                ha_test_smoke.enabled_entity_ids(entries),
            )
            results = ha_test_smoke.evaluate_state_health(entries, states)

            self.assertTrue(all(result.ok for result in results), results)
            self.assertIn(
                "2 optional DHE entities are waiting for real runtime values",
                [result.message for result in results],
            )

    def test_state_health_fails_disconnected_connection_sensor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "home-assistant_v2.db"
            _create_recorder_db(db_path)
            _insert_state(
                db_path,
                state_id=1,
                metadata_id=1,
                entity_id="climate.dhe_connect",
                state="heat",
                attributes={"connection_state": "connected"},
            )
            _insert_state(
                db_path,
                state_id=2,
                metadata_id=2,
                entity_id="sensor.dhe_connect_connection_state",
                state="reconnecting",
            )
            entries = [
                ha_test_smoke.EntityRegistryEntry(
                    "climate.dhe_connect",
                    "climate",
                    "stiebel_dhe_connect",
                ),
                ha_test_smoke.EntityRegistryEntry(
                    "sensor.dhe_connect_connection_state",
                    "sensor",
                    "stiebel_dhe_connect",
                ),
            ]

            states = ha_test_smoke.load_latest_states(
                db_path,
                ha_test_smoke.enabled_entity_ids(entries),
            )
            failures = [
                result.message
                for result in ha_test_smoke.evaluate_state_health(entries, states)
                if not result.ok
            ]

            self.assertIn("sensor.dhe_connect_connection_state='reconnecting'", failures)

    def test_state_health_checks_default_reconnect_count_object_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "home-assistant_v2.db"
            _create_recorder_db(db_path)
            _insert_state(
                db_path,
                state_id=1,
                metadata_id=1,
                entity_id="climate.dhe_connect",
                state="heat",
                attributes={"connection_state": "connected"},
            )
            _insert_state(
                db_path,
                state_id=2,
                metadata_id=2,
                entity_id="sensor.dhe_connect_connection_state",
                state="connected",
            )
            _insert_state(
                db_path,
                state_id=3,
                metadata_id=3,
                entity_id="sensor.dhe_connect_reconnect_count",
                state="2",
            )
            entries = [
                ha_test_smoke.EntityRegistryEntry(
                    "climate.dhe_connect",
                    "climate",
                    "stiebel_dhe_connect",
                ),
                ha_test_smoke.EntityRegistryEntry(
                    "sensor.dhe_connect_connection_state",
                    "sensor",
                    "stiebel_dhe_connect",
                ),
                ha_test_smoke.EntityRegistryEntry(
                    "sensor.dhe_connect_reconnect_count",
                    "sensor",
                    "stiebel_dhe_connect",
                ),
            ]

            states = ha_test_smoke.load_latest_states(
                db_path,
                ha_test_smoke.enabled_entity_ids(entries),
            )
            results = ha_test_smoke.evaluate_state_health(entries, states)

            self.assertTrue(all(result.ok for result in results), results)
            self.assertIn(
                "sensor.dhe_connect_reconnect_count='2' baseline reconnect count",
                [result.message for result in results],
            )

    def test_reconnect_stability_fails_on_monitor_increment(self) -> None:
        before = {
            "sensor.dhe_connect_reconnects": ha_test_smoke.LatestState(
                entity_id="sensor.dhe_connect_reconnects",
                state="1",
                attributes={},
                state_id=1,
                last_updated=1.0,
            )
        }
        after = {
            "sensor.dhe_connect_reconnects": ha_test_smoke.LatestState(
                entity_id="sensor.dhe_connect_reconnects",
                state="2",
                attributes={},
                state_id=2,
                last_updated=2.0,
            )
        }

        results = ha_test_smoke.evaluate_reconnect_stability(before, after)

        self.assertFalse(results[0].ok)
        self.assertEqual(
            results[0].message,
            "sensor.dhe_connect_reconnects reconnect count increased 1->2",
        )

    def test_reconnect_stability_allows_existing_baseline(self) -> None:
        before = {
            "sensor.dhe_connect_reconnects": ha_test_smoke.LatestState(
                entity_id="sensor.dhe_connect_reconnects",
                state="1",
                attributes={},
                state_id=1,
                last_updated=1.0,
            )
        }
        after = {
            "sensor.dhe_connect_reconnects": ha_test_smoke.LatestState(
                entity_id="sensor.dhe_connect_reconnects",
                state="1",
                attributes={},
                state_id=2,
                last_updated=2.0,
            )
        }

        results = ha_test_smoke.evaluate_reconnect_stability(before, after)

        self.assertTrue(results[0].ok)
        self.assertEqual(
            results[0].message,
            "sensor.dhe_connect_reconnects reconnect count stable at 1",
        )

    def test_recorder_write_counter_groups_by_entity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "home-assistant_v2.db"
            _create_recorder_db(db_path)
            _insert_state(
                db_path,
                state_id=1,
                metadata_id=1,
                entity_id="climate.dhe_connect",
                state="heat",
            )
            _insert_state(
                db_path,
                state_id=2,
                metadata_id=1,
                entity_id="climate.dhe_connect",
                state="heat",
            )
            _insert_state(
                db_path,
                state_id=3,
                metadata_id=2,
                entity_id="sensor.dhe_connect_reconnects",
                state="0",
            )

            writes = ha_test_smoke.count_recorder_writes(
                db_path,
                ["climate.dhe_connect", "sensor.dhe_connect_reconnects"],
                after_state_id=1,
            )

            self.assertEqual(
                writes,
                {
                    "climate.dhe_connect": 1,
                    "sensor.dhe_connect_reconnects": 1,
                },
            )

    def test_recorder_state_values_load_after_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "home-assistant_v2.db"
            _create_recorder_db(db_path)
            _insert_state(
                db_path,
                state_id=1,
                metadata_id=1,
                entity_id="sensor.dhe_connect_geratestatus",
                state="normal",
            )
            _insert_state(
                db_path,
                state_id=2,
                metadata_id=1,
                entity_id="sensor.dhe_connect_geratestatus",
                state="status_2",
            )
            _insert_state(
                db_path,
                state_id=3,
                metadata_id=1,
                entity_id="sensor.dhe_connect_geratestatus",
                state="normal",
            )

            values = ha_test_smoke.load_recorder_state_values(
                db_path,
                ["sensor.dhe_connect_geratestatus"],
                after_state_id=1,
            )

            self.assertEqual(
                values,
                {"sensor.dhe_connect_geratestatus": ["status_2", "normal"]},
            )

    def test_device_status_ids_use_registry_translation_key_and_recorder_fallback(
        self,
    ) -> None:
        entries = [
            ha_test_smoke.EntityRegistryEntry(
                "sensor.custom_device_mode",
                "sensor",
                "stiebel_dhe_connect",
                translation_key="device_status",
            ),
            ha_test_smoke.EntityRegistryEntry(
                "sensor.disabled_device_mode",
                "sensor",
                "stiebel_dhe_connect",
                disabled_by="user",
                translation_key="device_status",
            ),
        ]
        states = {
            "sensor.dhe_connect_geratestatus": ha_test_smoke.LatestState(
                entity_id="sensor.dhe_connect_geratestatus",
                state="status_2",
                attributes={},
                state_id=1,
                last_updated=1.0,
            )
        }

        entity_ids = ha_test_smoke.device_status_entity_ids(entries, states)

        self.assertEqual(
            entity_ids,
            ["sensor.custom_device_mode", "sensor.dhe_connect_geratestatus"],
        )

    def test_last_usage_duration_ids_use_registry_translation_key_and_fallback(
        self,
    ) -> None:
        entries = [
            ha_test_smoke.EntityRegistryEntry(
                "sensor.custom_usage_duration",
                "sensor",
                "stiebel_dhe_connect",
                translation_key="last_usage_time",
            ),
            ha_test_smoke.EntityRegistryEntry(
                "sensor.disabled_usage_duration",
                "sensor",
                "stiebel_dhe_connect",
                disabled_by="user",
                translation_key="last_usage_time",
            ),
        ]
        states = {
            "sensor.dhe_connect_letzte_nutzungsdauer": ha_test_smoke.LatestState(
                entity_id="sensor.dhe_connect_letzte_nutzungsdauer",
                state="2:34",
                attributes={},
                state_id=1,
                last_updated=1.0,
            )
        }

        entity_ids = ha_test_smoke.last_usage_duration_entity_ids(entries, states)

        self.assertEqual(
            entity_ids,
            [
                "sensor.custom_usage_duration",
                "sensor.dhe_connect_letzte_nutzungsdauer",
            ],
        )

    def test_recorder_window_detects_water_from_baseline_status(self) -> None:
        states = {
            "sensor.dhe_connect_geratestatus": ha_test_smoke.LatestState(
                entity_id="sensor.dhe_connect_geratestatus",
                state="status_2",
                attributes={},
                state_id=1,
                last_updated=1.0,
            )
        }

        self.assertTrue(
            ha_test_smoke.recorder_window_has_water_running(states, {})
        )

    def test_recorder_window_detects_water_from_status_history(self) -> None:
        self.assertTrue(
            ha_test_smoke.recorder_window_has_water_running(
                {},
                {"sensor.dhe_connect_geratestatus": ["normal", "status_2"]},
            )
        )

    def test_recorder_window_detects_completed_last_usage(self) -> None:
        reason = ha_test_smoke.recorder_operational_reason(
            baseline_status_states={},
            status_history={},
            last_usage_duration_history={
                "sensor.dhe_connect_letzte_nutzungsdauer": ["2:34"]
            },
        )

        self.assertEqual(
            reason,
            "completed usage detected via last usage duration",
        )

    def test_recorder_window_prefers_running_status_over_usage_duration(self) -> None:
        reason = ha_test_smoke.recorder_operational_reason(
            baseline_status_states={},
            status_history={"sensor.dhe_connect_geratestatus": ["status_2"]},
            last_usage_duration_history={
                "sensor.dhe_connect_letzte_nutzungsdauer": ["2:34"]
            },
        )

        self.assertEqual(reason, "water running detected via device status")

    def test_recorder_write_limits_are_skipped_while_water_runs(self) -> None:
        results = ha_test_smoke.evaluate_recorder_writes(
            {
                "sensor.dhe_connect_current_water_flow": 20,
                "sensor.dhe_connect_current_power": 8,
            },
            max_total_writes=10,
            max_entity_writes=5,
            operational_reason="water running detected via device status",
        )

        self.assertTrue(all(result.ok for result in results), results)
        self.assertIn("water running detected", results[0].message)
        self.assertIn("idle limits skipped", results[0].message)

    def test_recorder_write_limits_fail_for_idle_churn(self) -> None:
        results = ha_test_smoke.evaluate_recorder_writes(
            {"sensor.dhe_connect_current_water_flow": 20},
            max_total_writes=10,
            max_entity_writes=5,
        )

        self.assertFalse(results[0].ok)
        self.assertFalse(results[1].ok)

    def test_log_scan_reports_dhe_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir)
            (config / "home-assistant.log").write_text(
                "2026-05-16 ERROR custom_components.stiebel_dhe_connect boom\n",
                encoding="utf-8",
            )

            results = ha_test_smoke.scan_logs(config)

            self.assertFalse(results[0].ok)
            self.assertIn("stiebel_dhe_connect", results[0].message)

    def test_log_scan_redacts_auth_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir)
            private_host = ".".join(("172", "16", "1", "147"))
            (config / "home-assistant.log").write_text(
                "2026-05-16 ERROR custom_components.stiebel_dhe_connect "
                "access_token=abc123 refresh_token='def456' "
                f"Authorization: Bearer ghijk http://user:secret@{private_host}:8123\n",
                encoding="utf-8",
            )

            results = ha_test_smoke.scan_logs(config)

            self.assertFalse(results[0].ok)
            self.assertIn("<redacted>", results[0].message)
            self.assertIn("<private-host>", results[0].message)
            self.assertNotIn("abc123", results[0].message)
            self.assertNotIn("def456", results[0].message)
            self.assertNotIn("ghijk", results[0].message)
            self.assertNotIn("secret", results[0].message)
            self.assertNotIn(private_host, results[0].message)

    def test_log_scan_skips_when_no_log_sources_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            results = ha_test_smoke.scan_logs(Path(temp_dir))

            self.assertTrue(results[0].ok)
            self.assertIn("DHE log scan skipped", results[0].message)

    def test_log_scan_limits_itself_to_recent_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir)
            old_error = "2026-05-16 ERROR custom_components.stiebel_dhe_connect old\n"
            recent_lines = ["2026-05-16 INFO unrelated\n"] * 20_001
            (config / "home-assistant.log").write_text(
                old_error + "".join(recent_lines),
                encoding="utf-8",
            )

            results = ha_test_smoke.scan_logs(config)

            self.assertTrue(all(result.ok for result in results), results)

    def test_log_scan_reports_multiline_dhe_tracebacks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir)
            (config / "home-assistant.log").write_text(
                "\n".join(
                    [
                        "2026-05-16 ERROR [homeassistant] Error doing job",
                        "Traceback (most recent call last):",
                        '  File "/config/custom_components/stiebel_dhe_connect/client.py", line 1',
                        "RuntimeError: boom",
                    ]
                ),
                encoding="utf-8",
            )

            results = ha_test_smoke.scan_logs(config)

            self.assertFalse(results[0].ok)
            self.assertIn("stiebel_dhe_connect", results[0].message)

    def test_log_scan_ignores_unrelated_error_before_dhe_info(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir)
            (config / "home-assistant.log").write_text(
                "\n".join(
                    [
                        "2026-05-16 ERROR [homeassistant.components.mqtt] boom",
                        "2026-05-16 INFO custom_components.stiebel_dhe_connect ready",
                    ]
                ),
                encoding="utf-8",
            )

            results = ha_test_smoke.scan_logs(config)

            self.assertTrue(all(result.ok for result in results), results)


if __name__ == "__main__":
    unittest.main()
