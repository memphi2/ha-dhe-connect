"""Tests for Home Assistant config-entry diagnostics."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
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
    return _load_component_module("diagnostics")


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
            last_measurements={13: 20.5, 14: 30.0},
            last_app_values={
                "set:ste.app.weather:location": {
                    "Name": private_city,
                    "LocationId": "location-secret",
                }
            },
            last_device_info={
                "wlan_mac": private_mac,
                "device_id": "device-secret",
            },
            last_radio_state={"station": {"Name": private_station}},
            last_weather_state={"Location": {"Name": private_city}},
        )
        hass = types.SimpleNamespace(
            data={
                self.diagnostics.DOMAIN: {
                    entry.entry_id: types.SimpleNamespace(client=client),
                }
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
        self.assertEqual(result["runtime"]["cache"]["measurement_count"], 2)
        self.assertEqual(
            result["runtime"]["cache"]["app_value_keys"],
            ["set:ste.app.weather:location"],
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
            "device-secret",
            "location-secret",
            "255.255.255.0",
            "/24",
        ):
            self.assertNotIn(private_value, dumped)

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
        hass = types.SimpleNamespace(
            data={
                self.diagnostics.DOMAIN: {
                    entry.entry_id: types.SimpleNamespace(client=client),
                }
            }
        )

        result = asyncio.run(
            self.diagnostics.async_get_config_entry_diagnostics(hass, entry)
        )

        self.assertEqual(result["runtime"]["connection"]["reconnect_count"], 0)
        self.assertIsNone(result["config_entry"]["target"]["uses_default_port"])
        self.assertFalse(result["config_entry"]["target"]["custom_port"])


if __name__ == "__main__":
    unittest.main()
