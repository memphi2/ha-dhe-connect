"""Tests for DHE client value conversion helpers."""

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


def _load_client_value_helpers():
    _load_component_module("client_types")
    _load_component_module("protocol")
    return _load_component_module("client_value_helpers")


def _load_client_types():
    return _load_component_module("client_types")


class TestClientValueHelpers(unittest.TestCase):
    """Validate pure DHE value conversion helpers."""

    def setUp(self) -> None:
        self.helpers = _load_client_value_helpers()
        self.client_types = _load_client_types()
        self.protocol = _load_component_module("protocol")

    def test_temperature_rounding_and_clamping(self) -> None:
        self.assertEqual(self.helpers.round_to_half_c(42.24), 42.0)
        self.assertEqual(self.helpers.round_to_half_c(42.25), 42.0)
        self.assertEqual(self.helpers.round_to_half_c(42.26), 42.5)
        self.assertEqual(self.helpers.clamp(19.0, 20.0, 60.0), 20.0)
        self.assertEqual(self.helpers.clamp(61.0, 20.0, 60.0), 60.0)

    def test_raw_numeric_decoding_accepts_decimal_comma(self) -> None:
        self.assertEqual(self.helpers.c_to_raw_tenths(41.5), 415)
        self.assertEqual(self.helpers.raw_tenths_to_c(415), 41.5)
        self.assertEqual(self.helpers.raw_to_float(" 41,5 "), 41.5)

    def test_boolean_decoding_accepts_protocol_strings(self) -> None:
        self.assertTrue(self.helpers.raw_to_bool("true"))
        self.assertTrue(self.helpers.raw_to_bool("1"))
        self.assertFalse(self.helpers.raw_to_bool("off"))
        self.assertFalse(self.helpers.raw_to_bool(""))

    def test_water_heating_encoding_uses_protocol_raw_values(self) -> None:
        self.assertTrue(
            self.helpers.raw_to_water_heating_enabled(
                self.helpers.WATER_HEATING_ON_RAW
            )
        )
        self.assertFalse(
            self.helpers.raw_to_water_heating_enabled(
                self.helpers.WATER_HEATING_OFF_RAW
            )
        )
        self.assertEqual(
            self.helpers.water_heating_enabled_to_raw(True),
            self.helpers.WATER_HEATING_ON_RAW,
        )
        self.assertEqual(
            self.helpers.water_heating_enabled_to_raw(False),
            self.helpers.WATER_HEATING_OFF_RAW,
        )

    def test_requested_odb_zero_placeholder_filter_is_limited_to_selected_ids(
        self,
    ) -> None:
        self.assertFalse(
            self.helpers.should_publish_odb_readback(
                self.protocol.ID_HOT_WATER_VOLUME_TOTAL,
                "0",
                source=self.client_types.ODB_READ_SOURCE_REQUESTED,
            )
        )
        self.assertTrue(
            self.helpers.should_publish_odb_readback(
                self.protocol.ID_HOT_WATER_VOLUME_TOTAL,
                "1",
                source=self.client_types.ODB_READ_SOURCE_REQUESTED,
            )
        )
        self.assertTrue(
            self.helpers.should_publish_odb_readback(
                self.protocol.ID_HOT_WATER_VOLUME_TOTAL,
                "0",
                source=self.client_types.ODB_READ_SOURCE_RUNTIME,
            )
        )
        self.assertTrue(
            self.helpers.should_publish_odb_readback(
                self.protocol.ID_WATER_FLOW,
                "0",
                source=self.client_types.ODB_READ_SOURCE_REQUESTED,
            )
        )

    def test_temperature_memory_button_value_packs_address_and_temperature(self) -> None:
        self.assertEqual(self.helpers.build_req66(42.0, 5), (5 << 10) | 420)
        self.assertEqual(
            self.helpers.build_temperature_memory_button_value(42.0),
            self.helpers.build_req66(
                42.0,
                self.helpers.TEMPERATURE_MEMORY_BUTTON_ADDR,
            ),
        )

    def test_values_equal_uses_bool_identity_and_float_tolerance(self) -> None:
        self.assertTrue(self.helpers.values_equal(None, None))
        self.assertFalse(self.helpers.values_equal(None, 0))
        self.assertTrue(self.helpers.values_equal(True, 1))
        self.assertFalse(self.helpers.values_equal(True, 0))
        self.assertTrue(self.helpers.values_equal(42.0, 42.0005))
        self.assertFalse(self.helpers.values_equal(42.0, 42.01))


if __name__ == "__main__":
    unittest.main()
