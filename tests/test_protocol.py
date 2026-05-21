"""Tests for DHE protocol constants and command tables."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "custom_components" / "stiebel_dhe_connect" / "protocol.py"


def _load_protocol():
    spec = importlib.util.spec_from_file_location("protocol", PROTOCOL)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestODBProtocolConstants(unittest.TestCase):
    """Validate ODB ID tables."""

    def setUp(self) -> None:
        self.protocol = _load_protocol()

    def test_known_odb_ids_include_startup_writable_and_known_unexposed(self) -> None:
        known_ids = set(self.protocol.KNOWN_ODB_VALUE_IDS)

        self.assertIn(self.protocol.ID_SETPOINT, known_ids)
        self.assertIn(self.protocol.ID_DEVICE_STATUS, known_ids)
        self.assertIn(self.protocol.ID_WELLNESS_TIME_NORMALIZED, known_ids)
        self.assertIn(self.protocol.ID_CURRENCY_MODE, known_ids)
        self.assertIn(self.protocol.ID_SETPOINT_REQUEST, known_ids)

    def test_odb_handler_groups_cover_expected_ids(self) -> None:
        direct = set(self.protocol.ODB_DIRECT_HANDLER_IDS)
        tenths_temperature = set(self.protocol.ODB_TENTHS_TEMPERATURE_IDS)
        nonnegative = set(self.protocol.ODB_NONNEGATIVE_VALUE_IDS)
        deciliters = set(self.protocol.ODB_DECILITER_VALUE_IDS)
        ignored = set(self.protocol.ODB_IGNORED_VALUE_IDS)

        self.assertIn(self.protocol.ID_SETPOINT, direct)
        self.assertIn(self.protocol.ID_DEVICE_STATUS, direct)
        self.assertIn(self.protocol.ID_SCALD_PROTECTION_TEMPERATURE_LIMIT, tenths_temperature)
        self.assertIn(self.protocol.ID_WELLNESS_TIME_NORMALIZED, nonnegative)
        self.assertIn(self.protocol.ID_ODB_HOT_WATER_VOLUME, deciliters)
        self.assertEqual(
            set(self.protocol.ODB_ZERO_REQUEST_READBACK_IGNORE_IDS),
            {
                self.protocol.ID_ODB_HEATING_ENERGY,
                self.protocol.ID_ODB_HOT_WATER_VOLUME,
                self.protocol.ID_ODB_POSSIBLE_ENERGY_SAVING,
                self.protocol.ID_ODB_ACTUAL_WATER_SAVING,
                self.protocol.ID_WELLNESS_TIME_NORMALIZED,
            },
        )
        self.assertEqual(
            ignored,
            {self.protocol.ID_CURRENCY_MODE, self.protocol.ID_SETPOINT_REQUEST},
        )

        combined = direct | tenths_temperature | nonnegative | deciliters | ignored
        self.assertTrue(combined.issubset(set(self.protocol.KNOWN_ODB_VALUE_IDS)))

    def test_debug_names_cover_observed_raw_odb_ids(self) -> None:
        debug_names = self.protocol.ODB_DEBUG_NAMES

        self.assertEqual(debug_names[self.protocol.ID_SETPOINT], "ODB_So_WW_T")
        self.assertEqual(
            debug_names[self.protocol.ID_DEVICE_STATUS],
            "ODB_St_Geraet_Ba",
        )
        self.assertEqual(
            debug_names[self.protocol.ID_WELLNESS_TIME_NORMALIZED],
            "ODB_Wellness_Zeit_Norm",
        )

    def test_debug_name_reverse_map_is_one_to_one(self) -> None:
        self.assertEqual(
            len(self.protocol.ODB_DEBUG_NAMES),
            len(self.protocol.ODB_DEBUG_IDS),
        )
        self.assertEqual(
            len(self.protocol.ODB_DEBUG_IDS),
            len(self.protocol.ODB_DEBUG_IDS_CASEFOLD),
        )
        self.assertTrue(
            set(self.protocol.ODB_DEBUG_NAMES).issubset(
                set(self.protocol.KNOWN_ODB_VALUE_IDS)
            )
        )

    def test_debug_name_reverse_map_normalizes_odb_ids(self) -> None:
        self.assertEqual(
            self.protocol.ODB_DEBUG_IDS["ODB_Is_VS"],
            self.protocol.ID_WATER_FLOW,
        )
        self.assertEqual(
            self.protocol.normalize_odb_id("ODB_Is_VS"),
            self.protocol.ID_WATER_FLOW,
        )
        self.assertEqual(
            self.protocol.normalize_odb_id("odb_is_vs"),
            self.protocol.ID_WATER_FLOW,
        )
        self.assertEqual(
            self.protocol.normalize_odb_id(str(self.protocol.ID_WATER_FLOW)),
            self.protocol.ID_WATER_FLOW,
        )

        with self.assertRaises(ValueError):
            self.protocol.normalize_odb_id("ODB_Unknown")
        with self.assertRaises(ValueError):
            self.protocol.normalize_odb_id(-1)
        with self.assertRaises(ValueError):
            self.protocol.normalize_odb_id(True)

    def test_odb_error_names_normalize_debug_codes(self) -> None:
        self.assertEqual(self.protocol.ODB_ERROR_NAMES[0], "ODB_ERR_OK")
        self.assertEqual(
            self.protocol.odb_error_name(3),
            "ODB_ERR_MAX_LIMIT",
        )
        self.assertEqual(
            self.protocol.normalize_odb_error_code("ODB_ERR_MIN_LIMIT"),
            2,
        )
        self.assertEqual(
            self.protocol.normalize_odb_error_code("odb_err_wrong_psarea"),
            7,
        )
        self.assertEqual(
            self.protocol.normalize_odb_error_code("5"),
            5,
        )
        self.assertEqual(
            self.protocol.odb_error_name(99),
            "ODB_ERR_99",
        )
        self.assertEqual(self.protocol.odb_error_name("unknown"), "unknown")

        with self.assertRaises(ValueError):
            self.protocol.normalize_odb_error_code(-1)
        with self.assertRaises(ValueError):
            self.protocol.normalize_odb_error_code(True)

    def test_named_odb_commands_normalize_to_value_commands(self) -> None:
        self.assertEqual(
            self.protocol.normalize_odb_command(
                "set:ste.common.odb:ODB_Is_VS",
                27,
            ),
            (self.protocol.ODB_SET_COMMAND, self.protocol.ID_WATER_FLOW),
        )
        self.assertEqual(
            self.protocol.normalize_odb_command(
                self.protocol.ODB_GET_COMMAND,
                {"name": "ODB_Is_VS", "value": ""},
            ),
            (self.protocol.ODB_GET_COMMAND, self.protocol.ID_WATER_FLOW),
        )
        self.assertEqual(
            self.protocol.normalize_odb_command(
                self.protocol.ODB_GET_COMMAND,
                {"id": "", "name": "ODB_Is_VS", "value": ""},
            ),
            (self.protocol.ODB_GET_COMMAND, self.protocol.ID_WATER_FLOW),
        )
        self.assertEqual(
            self.protocol.normalize_odb_command(
                self.protocol.ODB_GET_COMMAND,
                {"id": None, "debugName": "ODB_Is_VS", "value": ""},
            ),
            (self.protocol.ODB_GET_COMMAND, self.protocol.ID_WATER_FLOW),
        )
        self.assertEqual(
            self.protocol.normalize_odb_command(
                self.protocol.ODB_GET_COMMAND,
                {
                    "id": self.protocol.ID_WATER_FLOW,
                    "debug_name": "ODB_Is_VS",
                    "value": "",
                },
            ),
            (self.protocol.ODB_GET_COMMAND, self.protocol.ID_WATER_FLOW),
        )

    def test_named_odb_command_rejects_conflicting_id_hints(self) -> None:
        with self.assertRaises(ValueError):
            self.protocol.normalize_odb_command(
                self.protocol.ODB_SET_COMMAND,
                {
                    "id": self.protocol.ID_WATER_FLOW,
                    "name": "ODB_Is_P_Norm",
                    "value": 27,
                },
            )

        with self.assertRaises(ValueError):
            self.protocol.normalize_odb_command(
                "set:ste.common.odb:ODB_Is_VS",
                {
                    "id": self.protocol.ID_POWER_PERCENT,
                    "value": 27,
                },
            )

    def test_price_component_tables_keep_euros_and_cents_grouped(self) -> None:
        electricity_group = self.protocol.PRICE_COMPONENT_IDS[
            self.protocol.ID_ELECTRICITY_PRICE_CENTS
        ]
        water_group = self.protocol.PRICE_COMPONENT_IDS[
            self.protocol.ID_WATER_PRICE_EUROS
        ]

        self.assertEqual(
            electricity_group,
            (
                self.protocol.ID_ELECTRICITY_PRICE,
                self.protocol.ID_ELECTRICITY_PRICE_EUROS,
                self.protocol.ID_ELECTRICITY_PRICE_CENTS,
            ),
        )
        self.assertEqual(
            water_group,
            (
                self.protocol.ID_WATER_PRICE,
                self.protocol.ID_WATER_PRICE_EUROS,
                self.protocol.ID_WATER_PRICE_CENTS,
            ),
        )


class TestAppCommandTables(unittest.TestCase):
    """Validate derived app command sets."""

    def setUp(self) -> None:
        self.protocol = _load_protocol()

    def test_timer_commands_are_derived_for_brush_and_shower_paths(self) -> None:
        self.assertEqual(
            set(self.protocol.APP_TIMER_REQUEST_COMMANDS),
            {
                "get:ste.app.brushTimer:activation",
                "get:ste.app.brushTimer:durationMilliseconds",
                "get:ste.app.brushTimer:remainingMilliseconds",
                "get:ste.app.showerTimer:activation",
                "get:ste.app.showerTimer:durationMilliseconds",
                "get:ste.app.showerTimer:remainingMilliseconds",
            },
        )
        self.assertIn(
            "assign:ste.app.brushTimer:activation",
            self.protocol.APP_TIMER_ASSIGN_COMMANDS,
        )
        self.assertIn(
            "get:ste.app.brushTimer:activation",
            self.protocol.APP_TIMER_VALUE_COMMANDS,
        )
        self.assertIn(
            "get:ste.app.showerTimer:durationMilliseconds",
            self.protocol.APP_TIMER_VALUE_COMMANDS,
        )
        self.assertNotIn(
            "assign:ste.app.brushTimer:remainingMilliseconds",
            self.protocol.APP_TIMER_ASSIGN_COMMANDS,
        )

    def test_radio_startup_requests_are_small_but_catalogs_are_known(self) -> None:
        startup_requests = set(self.protocol.RADIO_REQUEST_COMMANDS)
        known_requests = self.protocol.RADIO_KNOWN_REQUEST_COMMANDS

        self.assertIn("get:ste.app.radio:station", startup_requests)
        self.assertIn("get:ste.app.radio:favorites", startup_requests)
        self.assertNotIn("get:ste.app.radio:city", startup_requests)
        self.assertIn("get:ste.app.radio:city", known_requests)
        self.assertIn("get:ste.app.radio:stations", known_requests)

    def test_weather_startup_requests_skip_large_catalogs(self) -> None:
        startup_requests = set(self.protocol.WEATHER_REQUEST_COMMANDS)

        self.assertEqual(
            startup_requests,
            {
                "get:ste.app.weather:location",
                "get:ste.app.weather:favorites",
                "get:ste.app.weather:country",
            },
        )
        self.assertIn(
            "set:ste.app.weather:countries",
            self.protocol.WEATHER_SET_COMMANDS,
        )

    def test_consumption_and_saving_monitor_requests_match_set_commands(self) -> None:
        expected_consumption = {
            command.replace("set:", "get:", 1)
            for command in self.protocol.CONSUMPTION_COMMAND_IDS
        }
        expected_saving_monitor = {
            command.replace("set:", "get:", 1)
            for command in self.protocol.SAVING_MONITOR_SET_COMMANDS
        }

        self.assertEqual(
            set(self.protocol.CONSUMPTION_REQUEST_COMMANDS),
            expected_consumption,
        )
        self.assertEqual(
            set(self.protocol.SAVING_MONITOR_REQUEST_COMMANDS),
            expected_saving_monitor,
        )

    def test_app_startup_set_commands_match_startup_requests(self) -> None:
        expected = {
            command.replace("get:", "set:", 1)
            for command in self.protocol.APP_STARTUP_REQUEST_COMMANDS
        }

        self.assertEqual(self.protocol.APP_STARTUP_SET_COMMANDS, expected)
        self.assertIn(
            "get:ste.app.wellness:programs",
            self.protocol.APP_STARTUP_REQUEST_COMMANDS,
        )

    def test_protocol_exports_only_constant_names(self) -> None:
        exported = set(self.protocol.__all__)

        self.assertIn("NS", exported)
        self.assertIn("ID_SETPOINT", exported)
        self.assertIn("RADIO_REQUEST_COMMANDS", exported)
        self.assertNotIn("annotations", exported)


if __name__ == "__main__":
    unittest.main()
