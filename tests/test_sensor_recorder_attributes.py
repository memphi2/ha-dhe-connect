"""Tests for recorder attribute exclusions on sensor entities."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_sensor_module():
    from custom_components.stiebel_dhe_connect import sensor as sensor_module

    return sensor_module


class TestSensorRecorderAttributes(unittest.TestCase):
    """Validate unrecorded dynamic attributes for recorder safety."""

    def test_stiebel_sensor_excludes_heavy_dynamic_attributes(self) -> None:
        sensor_module = _load_sensor_module()
        attributes = sensor_module.StiebelDHESensor._unrecorded_attributes

        self.assertIn("chart", attributes)
        self.assertIn("possible", attributes)
        self.assertIn("real", attributes)
        self.assertIn("consumption", attributes)
        self.assertIn("activation_rate", attributes)


if __name__ == "__main__":
    unittest.main()
