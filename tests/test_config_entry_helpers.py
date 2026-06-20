"""Tests for config-entry helper functions."""

from __future__ import annotations

import importlib.util
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


def _load_module():
    _load_component_module("connection_helpers")
    _load_component_module("const")
    return _load_component_module("config_entry_helpers")


class TestConfigEntryHelpers(unittest.TestCase):
    """Validate config-entry host/port helpers."""

    def setUp(self) -> None:
        self.helpers = _load_module()

    def test_entry_target_normalizes_host_and_port(self) -> None:
        entry = types.SimpleNamespace(
            data={"host": " DHE-Connect.local.", "port": "8443"},
            options={"port": 9443},
        )
        self.assertEqual(("dhe-connect.local", 9443), self.helpers.entry_target(entry))

    def test_entry_target_is_none_when_host_missing(self) -> None:
        entry = types.SimpleNamespace(data={}, options={})
        self.assertIsNone(self.helpers.entry_target(entry))

    def test_entry_target_is_none_for_invalid_host(self) -> None:
        entry = types.SimpleNamespace(
            data={"host": "dhe-connect.local:8443", "port": 8443},
            options={},
        )
        self.assertIsNone(self.helpers.entry_target(entry))

    def test_entry_target_is_none_for_float_port(self) -> None:
        entry = types.SimpleNamespace(
            data={"host": "dhe-connect.local", "port": 8443.0}, options={}
        )
        self.assertIsNone(self.helpers.entry_target(entry))

    def test_entry_target_is_none_for_bool_port(self) -> None:
        entry = types.SimpleNamespace(
            data={"host": "dhe-connect.local", "port": True}, options={}
        )
        self.assertIsNone(self.helpers.entry_target(entry))

    def test_is_target_used_by_other_entry_uses_normalized_targets(self) -> None:
        entry_one = types.SimpleNamespace(
            entry_id="one",
            data={"host": "DHE-Connect.local", "port": 8443},
            options={},
        )
        entry_two = types.SimpleNamespace(
            entry_id="two",
            data={"host": "other.local", "port": 9443},
            options={},
        )
        config_entries = types.SimpleNamespace(
            async_entries=lambda domain: (
                [entry_one, entry_two] if domain == self.helpers.DOMAIN else []
            ),
        )
        hass = types.SimpleNamespace(config_entries=config_entries)

        self.assertTrue(
            self.helpers.is_target_used_by_other_entry(
                hass,
                "dhe-connect.local",
                8443,
            )
        )
        self.assertFalse(
            self.helpers.is_target_used_by_other_entry(
                hass,
                "dhe-connect.local",
                9443,
                exclude_entry_id="one",
            )
        )


if __name__ == "__main__":
    unittest.main()
