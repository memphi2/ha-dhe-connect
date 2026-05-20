"""Tests for Home Assistant config-entry diagnostics."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMPONENT_DIR = ROOT / "custom_components" / "stiebel_dhe_connect"
PACKAGE_NAME = "custom_components.stiebel_dhe_connect"


def _load_component_module(module_name: str):
    try:
        from tests.test_ha_stubs import ensure_homeassistant_stubs
    except ModuleNotFoundError:
        from test_ha_stubs import ensure_homeassistant_stubs

    ensure_homeassistant_stubs()
    root_module_name = "custom_components"
    if root_module_name not in sys.modules:
        root_module = types.ModuleType(root_module_name)
        root_module.__path__ = [str(ROOT / root_module_name)]
        sys.modules[root_module_name] = root_module

    package = sys.modules.get(PACKAGE_NAME)
    if package is None:
        package = types.ModuleType(PACKAGE_NAME)
        package.__path__ = [str(COMPONENT_DIR)]
        package.__package__ = root_module_name
        sys.modules[PACKAGE_NAME] = package

    module_filename = COMPONENT_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE_NAME}.{module_name}",
        module_filename,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[f"{PACKAGE_NAME}.{module_name}"] = module
    spec.loader.exec_module(module)
    return module


def _load_diagnostics():
    _load_component_module("connection_helpers")
    _load_component_module("const")
    _load_component_module("client_diagnostics")
    _load_component_module("config_entry_helpers")
    _load_component_module("setup_scan")
    _load_component_module("device_info_helpers")
    _load_component_module("discovery_state")
    return _load_component_module("diagnostics")


class _FakeConfig:
    def __init__(self, root: Path) -> None:
        self._root = root

    def path(self, relative: str) -> str:
        return str(self._root / relative)


class _FakeHass:
    def __init__(self, root: Path, data: dict[str, object] | None = None) -> None:
        self.config = _FakeConfig(root)
        self.data: dict[str, object] = data or {}

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class TestConfigEntryDiagnostics(unittest.TestCase):
    """Validate the support diagnostics payload is useful and anonymized."""

    def setUp(self) -> None:
        self.diagnostics = _load_diagnostics()

    def test_config_entry_diagnostics_redacts_private_context(self) -> None:
        private_host = ".".join(("172", "16", "2", "124"))
        private_subnet = ".".join(("172", "16", "2", "0"))
        private_local = "dhe-ja06.local"
        private_mac = "aa:bb:cc:dd:ee:ff"
        private_name = "Private Bathroom DHE"
        private_token = "token-secret"
        private_city = "Private City"
        private_station = "Private Radio"

        entry = types.SimpleNamespace(
            entry_id="entry-secret",
            source="user",
            version=1,
            minor_version=1,
            unique_id=private_mac,
            data={
                "host": private_host,
                "port": 8443,
                "name": private_name,
                "token_file": ".storage/stiebel_dhe_connect_token_secret.txt",
                "scan_network_address": private_subnet,
                "scan_netmask": "255.255.255.0",
            },
            options={
                "token": private_token,
                "scan_cidr": f"{private_subnet}/24",
                "internal_scald_protection": 60,
            },
        )
        client = types.SimpleNamespace(
            available=True,
            online=True,
            reconnect_count=2,
            diagnostic_state={
                "connection_state": "connected",
                "session_id": "sid-secret",
                "last_reconnect_reason": (
                    f"GET http://{private_local}:8443/?token={private_token} "
                    f"fallback=http://{private_host}:8443 "
                    f"raw_host={private_host}:8443 mdns={private_local}:8443 "
                    f"mac={private_mac}"
                ),
            },
            reconnect_supervisor_state={
                "attempts": 1,
                "successful_reconnect_count": 2,
                "average_reconnect_interval_seconds": 4.5,
                "last_successful_reconnect_duration_seconds": 3.0,
                "next_delay_seconds": 2.0,
                "in_grace_period": True,
                "should_mark_unavailable": False,
                "grace_seconds_remaining": 12.5,
                "base_delay_seconds": 2.0,
                "max_delay_seconds": 180.0,
                "stable_reset_after_seconds": 60.0,
                "grace_period_seconds": 15.0,
            },
            transport_statistics={
                "websocket_upgrade_failures": 3,
            },
            runtime_parser_statistics={
                "message_count": 12,
                "last_category": "odb_value",
                "counts": {
                    "odb_value": 8,
                    "weather_state": 2,
                    "radio_state": 2,
                },
            },
            last_measurements={13: 20.5, 14: 30.0},
            last_app_values={
                "set:ste.app.weather:location": {
                    "Name": private_city,
                    "LocationId": "location-secret",
                }
            },
            last_device_info={
                "device_type": "DHE Connect",
                "wlan_mac": private_mac,
                "bluetooth_mac": "11:22:33:44:55:66",
                "device_id": "1234567-private-tail",
                "product_id_prefix": "1234567",
                "protocol_version": "1.9.00",
                "web_app_version": "1.9.00",
                "raw_odb_protocol_version": 1,
            },
            last_radio_state={"station": {"Name": private_station}},
            last_weather_state={"Location": {"Name": private_city}},
        )
        entry.runtime_data = types.SimpleNamespace(client=client)
        now = time.time()
        hass = types.SimpleNamespace(
            data={
                f"{self.diagnostics.DOMAIN}_discovery": {
                    "version": 1,
                    "records": {
                        f"zeroconf:{private_host}:8443": {
                            "source": "zeroconf",
                            "host": private_host,
                            "port": 8443,
                            "hostname": private_local,
                            "service_name": f"{private_name}._ste-dhe._tcp.local.",
                            "ip_address": private_host,
                            "confidence": 90,
                            "preferred_identity_source": "hostname",
                            "identity_conflicts": [],
                            "evidence": ["dhe_service_type"],
                            "first_seen": "2026-05-19T10:00:00Z",
                            "first_seen_ts": now,
                            "last_seen": "2026-05-19T10:00:00Z",
                            "last_seen_ts": now,
                            "seen_count": 1,
                            "prompt_count": 1,
                        }
                    },
                },
            }
        )

        result = asyncio.run(
            self.diagnostics.async_get_config_entry_diagnostics(hass, entry)
        )
        dumped = json.dumps(result, sort_keys=True)

        self.assertEqual(result["integration"]["domain"], self.diagnostics.DOMAIN)
        self.assertEqual(result["integration"]["diagnostics_schema"], 1)
        self.assertTrue(result["config_entry"]["target"]["has_host"])
        self.assertTrue(result["config_entry"]["target"]["uses_default_port"])
        self.assertFalse(result["config_entry"]["target"]["custom_port"])
        self.assertTrue(result["runtime"]["loaded"])
        self.assertEqual(result["runtime"]["connection"]["reconnect_count"], 2)
        diagnostic_state = result["runtime"]["connection"]["diagnostic_state"]
        diagnostic_state_dump = json.dumps(diagnostic_state, sort_keys=True)
        supervisor_state = result["runtime"]["connection"]["reconnect_supervisor"]
        self.assertEqual(supervisor_state["attempts"], 1)
        self.assertEqual(supervisor_state["successful_reconnect_count"], 2)
        self.assertEqual(supervisor_state["average_reconnect_interval_seconds"], 4.5)
        self.assertEqual(
            supervisor_state["last_successful_reconnect_duration_seconds"], 3.0
        )
        self.assertTrue(supervisor_state["in_grace_period"])
        self.assertFalse(supervisor_state["should_mark_unavailable"])
        self.assertEqual(supervisor_state["next_delay_seconds"], 2.0)
        self.assertEqual(
            result["runtime"]["transport"]["websocket_upgrade_failures"], 3
        )
        self.assertEqual(result["runtime"]["runtime_parser"]["message_count"], 12)
        self.assertEqual(
            result["runtime"]["runtime_parser"]["last_category"], "odb_value"
        )
        self.assertEqual(
            result["runtime"]["runtime_parser"]["category_counts"],
            {
                "odb_value": 8,
                "radio_state": 2,
                "weather_state": 2,
            },
        )
        self.assertEqual(result["runtime"]["cache"]["measurement_count"], 2)
        self.assertEqual(result["runtime"]["cache"]["measurement_ids"], ["13", "14"])
        self.assertEqual(result["runtime"]["cache"]["app_value_count"], 1)
        self.assertEqual(
            result["runtime"]["cache"]["app_value_keys"],
            ["set:ste.app.weather:location"],
        )
        self.assertEqual(
            result["runtime"]["cache"]["device_info_keys"],
            [
                "bluetooth_mac",
                "device_id",
                "device_type",
                "product_id_prefix",
                "protocol_version",
                "raw_odb_protocol_version",
                "web_app_version",
                "wlan_mac",
            ],
        )
        self.assertEqual(result["runtime"]["device"]["device_type"], "DHE Connect")
        self.assertEqual(result["runtime"]["device"]["product_id_prefix"], "1234567")
        self.assertEqual(result["runtime"]["device"]["protocol_version"], "1.9.00")
        self.assertEqual(result["runtime"]["device"]["web_app_version"], "1.9.00")
        self.assertEqual(result["runtime"]["device"]["raw_odb_protocol_version"], 1)
        self.assertTrue(result["runtime"]["device"]["has_wlan_mac"])
        self.assertTrue(result["runtime"]["device"]["has_bluetooth_mac"])
        self.assertEqual(result["runtime"]["cache"]["radio_state_keys"], ["station"])
        self.assertEqual(result["runtime"]["cache"]["weather_state_keys"], ["Location"])
        self.assertTrue(result["discovery"]["loaded"])
        self.assertEqual(result["discovery"]["sources"], {"zeroconf": 1})
        self.assertEqual(result["discovery"]["cache_state"]["stored_record_count"], 1)
        self.assertEqual(result["discovery"]["cache_state"]["recent_record_count"], 1)
        self.assertEqual(result["discovery"]["cache_state"]["expired_record_count"], 0)
        self.assertEqual(result["discovery"]["zeroconf_cache"]["record_count"], 1)
        self.assertEqual(
            result["discovery"]["zeroconf_cache"]["recent_record_count"],
            1,
        )
        self.assertIsInstance(
            result["discovery"]["zeroconf_cache"]["newest_age_seconds"],
            int,
        )

        for private_value in (
            private_host,
            private_subnet,
            private_local,
            private_mac,
            private_name,
            private_token,
            private_city,
            private_station,
            "sid-secret",
            "1234567-private-tail",
            "location-secret",
            "255.255.255.0",
            "/24",
        ):
            self.assertNotIn(private_value, dumped)
            self.assertNotIn(private_value, diagnostic_state_dump)

        self.assertIn("1234567", dumped)

        self.assertNotIn('"port": 8443', dumped)
        self.assertIn("<private-host>", dumped)
        self.assertIn("<local-host>", dumped)
        self.assertIn("<host>", dumped)
        self.assertIn("<mac-address>", dumped)
        self.assertIn(self.diagnostics.REDACTED, dumped)

    def test_config_entry_diagnostics_handles_unloaded_entry(self) -> None:
        entry = types.SimpleNamespace(
            entry_id="entry-secret",
            source="user",
            version=1,
            minor_version=1,
            unique_id=None,
            data={},
            options={},
        )
        hass = types.SimpleNamespace(data={self.diagnostics.DOMAIN: {}})

        result = asyncio.run(
            self.diagnostics.async_get_config_entry_diagnostics(hass, entry)
        )

        self.assertFalse(result["runtime"]["loaded"])
        self.assertFalse(result["config_entry"]["target"]["has_host"])
        self.assertIsNone(result["config_entry"]["target"]["uses_default_port"])
        self.assertFalse(result["config_entry"]["target"]["custom_port"])

    def test_config_entry_diagnostics_loads_persisted_discovery_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_path = root / ".storage" / "stiebel_dhe_connect_discovery_cache"
            cache_path.parent.mkdir(parents=True)
            cache_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "records": {
                            "zeroconf:dhe-ja06.local:8443": {
                                "source": "zeroconf",
                                "host": "192.0.2.124",
                                "port": 8443,
                                "name": "DHE-JA06",
                                "hostname": "dhe-ja06.local",
                                "service_name": "DHE-JA06._ste-dhe._tcp.local.",
                                "ip_address": "192.0.2.124",
                                "confidence": 90,
                                "preferred_identity_source": "hostname",
                                "identity_conflicts": [],
                                "evidence": ["dhe_service_type"],
                                "first_seen": "2026-05-19T10:00:00Z",
                                "first_seen_ts": time.time(),
                                "last_seen": "2026-05-19T10:00:00Z",
                                "last_seen_ts": time.time(),
                                "seen_count": 1,
                                "prompt_count": 1,
                            },
                        },
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            entry = types.SimpleNamespace(
                entry_id="entry-secret",
                source="user",
                version=1,
                minor_version=1,
                unique_id=None,
                data={},
                options={},
            )
            hass = _FakeHass(root, {self.diagnostics.DOMAIN: {}})

            result = asyncio.run(
                self.diagnostics.async_get_config_entry_diagnostics(hass, entry)
            )

            self.assertTrue(result["discovery"]["loaded"])
            self.assertEqual(result["discovery"]["sources"], {"zeroconf": 1})
            self.assertEqual(result["discovery"]["recent_record_count"], 1)
            self.assertTrue(result["discovery"]["cache_state"]["version_supported"])
            self.assertEqual(
                result["discovery"]["cache_state"]["stored_record_count"], 1
            )
            self.assertEqual(result["discovery"]["zeroconf_cache"]["record_count"], 1)
            self.assertEqual(
                result["discovery"]["zeroconf_cache"]["recent_record_count"],
                1,
            )
            self.assertIsInstance(
                result["discovery"]["zeroconf_cache"]["newest_age_seconds"],
                int,
            )

    def test_config_entry_diagnostics_tolerates_invalid_reconnect_count(self) -> None:
        entry = types.SimpleNamespace(
            entry_id="entry-secret",
            source="user",
            version=1,
            minor_version=1,
            unique_id=None,
            data={"host": "dhe.local", "port": "not-a-port"},
            options={},
        )
        client = types.SimpleNamespace(reconnect_count=None)
        entry.runtime_data = types.SimpleNamespace(client=client)
        hass = types.SimpleNamespace(data={})

        result = asyncio.run(
            self.diagnostics.async_get_config_entry_diagnostics(hass, entry)
        )

        self.assertEqual(result["runtime"]["connection"]["reconnect_count"], 0)
        self.assertIsNone(result["config_entry"]["target"]["uses_default_port"])
        self.assertFalse(result["config_entry"]["target"]["custom_port"])


if __name__ == "__main__":
    unittest.main()
