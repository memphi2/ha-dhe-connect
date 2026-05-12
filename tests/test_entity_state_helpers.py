"""Tests for pure entity state helper behavior."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ENTITY_STATE_HELPERS = (
    ROOT / "custom_components" / "stiebel_dhe_connect" / "entity_state_helpers.py"
)


def _load_entity_state_helpers():
    spec = importlib.util.spec_from_file_location(
        "entity_state_helpers",
        ENTITY_STATE_HELPERS,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestValueConversionHelpers(unittest.TestCase):
    """Validate shared value conversion rules."""

    def setUp(self) -> None:
        self.helpers = _load_entity_state_helpers()

    def test_coerce_float_accepts_numbers_and_numeric_strings(self) -> None:
        self.assertEqual(self.helpers.coerce_float(12), 12.0)
        self.assertEqual(self.helpers.coerce_float(12.5), 12.5)
        self.assertEqual(self.helpers.coerce_float("12.5"), 12.5)

    def test_coerce_float_rejects_missing_invalid_and_bool_values(self) -> None:
        self.assertIsNone(self.helpers.coerce_float(None))
        self.assertIsNone(self.helpers.coerce_float(""))
        self.assertIsNone(self.helpers.coerce_float("not-a-number"))
        self.assertIsNone(self.helpers.coerce_float(True))
        self.assertIsNone(self.helpers.coerce_float(False))

    def test_format_minutes_duration_rounds_to_seconds(self) -> None:
        self.assertEqual(self.helpers.format_minutes_duration(0), "0:00")
        self.assertEqual(self.helpers.format_minutes_duration(1), "1:00")
        self.assertEqual(self.helpers.format_minutes_duration(1.5), "1:30")
        self.assertEqual(self.helpers.format_minutes_duration(1.499), "1:30")

    def test_format_minutes_duration_clamps_negative_values(self) -> None:
        self.assertEqual(self.helpers.format_minutes_duration(-1), "0:00")

    def test_format_minutes_duration_rejects_non_numeric_values(self) -> None:
        self.assertIsNone(self.helpers.format_minutes_duration(None))
        self.assertIsNone(self.helpers.format_minutes_duration(""))
        self.assertIsNone(self.helpers.format_minutes_duration("abc"))

    def test_minutes_to_seconds_preserves_half_minute_values(self) -> None:
        self.assertEqual(self.helpers.minutes_to_seconds(1), 60.0)
        self.assertEqual(self.helpers.minutes_to_seconds(1.5), 90.0)
        self.assertEqual(self.helpers.minutes_to_seconds("20"), 1200.0)

    def test_seconds_to_minutes_preserves_half_minute_values(self) -> None:
        self.assertEqual(self.helpers.seconds_to_minutes(60), 1.0)
        self.assertEqual(self.helpers.seconds_to_minutes(90), 1.5)
        self.assertEqual(self.helpers.seconds_to_minutes("1200"), 20.0)

    def test_seconds_to_minutes_preserves_single_second_values(self) -> None:
        minutes = self.helpers.seconds_to_minutes(61)

        self.assertIsNotNone(minutes)
        self.assertEqual(round(minutes * 60000), 61000)

    def test_duration_unit_conversion_rejects_invalid_values(self) -> None:
        self.assertIsNone(self.helpers.minutes_to_seconds(True))
        self.assertIsNone(self.helpers.seconds_to_minutes(False))
        self.assertIsNone(self.helpers.minutes_to_seconds("abc"))
        self.assertIsNone(self.helpers.seconds_to_minutes(None))

    def test_duration_part_helpers_split_whole_seconds(self) -> None:
        self.assertEqual(self.helpers.duration_minutes_part(305), 5)
        self.assertEqual(self.helpers.duration_seconds_part(305), 5)
        self.assertEqual(self.helpers.duration_minutes_part(1200), 20)
        self.assertEqual(self.helpers.duration_seconds_part(1200), 0)

    def test_replace_duration_part_clamps_total_duration(self) -> None:
        self.assertEqual(
            self.helpers.replace_duration_part(
                300,
                "minutes",
                4,
                minimum=60,
                maximum=1200,
            ),
            240,
        )
        self.assertEqual(
            self.helpers.replace_duration_part(
                305,
                "seconds",
                30,
                minimum=60,
                maximum=1200,
            ),
            330,
        )
        self.assertEqual(
            self.helpers.replace_duration_part(
                1200,
                "seconds",
                30,
                minimum=60,
                maximum=1200,
            ),
            1200,
        )


class TestAvailabilityHelpers(unittest.TestCase):
    """Validate shared availability decisions."""

    def setUp(self) -> None:
        self.helpers = _load_entity_state_helpers()

    def test_value_available_requires_connection_and_known_value(self) -> None:
        self.assertTrue(self.helpers.value_available(True, 0))
        self.assertTrue(self.helpers.value_available(True, False))
        self.assertFalse(self.helpers.value_available(True, None))
        self.assertFalse(self.helpers.value_available(False, 1))

    def test_connected_or_known_available_accepts_cached_values(self) -> None:
        self.assertTrue(self.helpers.connected_or_known_available(True, None))
        self.assertTrue(self.helpers.connected_or_known_available(False, 0))
        self.assertTrue(self.helpers.connected_or_known_available(False, False))
        self.assertFalse(self.helpers.connected_or_known_available(False, None))
        self.assertFalse(
            self.helpers.connected_or_known_available(False, None, None)
        )

    def test_connected_and_ready_requires_both_flags(self) -> None:
        self.assertTrue(self.helpers.connected_and_ready(True, True))
        self.assertFalse(self.helpers.connected_and_ready(True, False))
        self.assertFalse(self.helpers.connected_and_ready(False, True))


class TestMeasurementAttributeHelpers(unittest.TestCase):
    """Validate shared measurement attribute handling."""

    def setUp(self) -> None:
        self.helpers = _load_entity_state_helpers()

    def test_measurement_attribute_text_returns_non_empty_text(self) -> None:
        self.assertEqual(
            self.helpers.measurement_attribute_text({"name": "Memory 1"}, "name"),
            "Memory 1",
        )
        self.assertEqual(
            self.helpers.measurement_attribute_text({"name": 123}, "name"),
            "123",
        )

    def test_measurement_attribute_text_rejects_missing_and_empty_values(self) -> None:
        self.assertIsNone(self.helpers.measurement_attribute_text({}, "name"))
        self.assertIsNone(
            self.helpers.measurement_attribute_text({"name": None}, "name")
        )
        self.assertIsNone(self.helpers.measurement_attribute_text({"name": ""}, "name"))

    def test_merge_state_attributes_prefers_dynamic_values(self) -> None:
        base = {"odb_id": 1, "unit": "minutes"}
        dynamic = {"unit": "seconds", "name": "Timer"}

        merged = self.helpers.merge_state_attributes(base, dynamic)

        self.assertEqual(
            merged,
            {"odb_id": 1, "unit": "seconds", "name": "Timer"},
        )

    def test_merge_state_attributes_does_not_mutate_inputs(self) -> None:
        base = {"temperature_memory_slot": 1}
        dynamic = {"name": "Morning"}

        merged = self.helpers.merge_state_attributes(base, dynamic)
        merged["name"] = "Changed"

        self.assertEqual(base, {"temperature_memory_slot": 1})
        self.assertEqual(dynamic, {"name": "Morning"})

    def test_merge_state_attributes_ignores_non_mapping_dynamic_values(self) -> None:
        self.assertEqual(
            self.helpers.merge_state_attributes({"odb_id": 1}, None),
            {"odb_id": 1},
        )
        self.assertEqual(
            self.helpers.merge_state_attributes({"odb_id": 1}, ["bad"]),
            {"odb_id": 1},
        )


if __name__ == "__main__":
    unittest.main()
