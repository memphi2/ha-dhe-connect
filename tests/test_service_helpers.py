"""Tests for service metadata helpers and static service declarations."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVICE_HELPERS = (
    ROOT / "custom_components" / "stiebel_dhe_connect" / "service_helpers.py"
)
SERVICES_YAML = ROOT / "custom_components" / "stiebel_dhe_connect" / "services.yaml"


def _load_service_helpers():
    spec = importlib.util.spec_from_file_location("service_helpers", SERVICE_HELPERS)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _result_number_max_values(text: str) -> list[int]:
    values: list[int] = []
    in_result_number = False
    result_indent = 0

    for line in text.splitlines():
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if stripped == "result_number:":
            in_result_number = True
            result_indent = indent
            continue
        if in_result_number and stripped and indent <= result_indent:
            in_result_number = False
        if in_result_number and stripped.startswith("max:"):
            values.append(int(stripped.split(":", 1)[1].strip()))

    return values


class TestServiceHelpers(unittest.TestCase):
    """Validate service constants stay aligned with services.yaml."""

    def setUp(self) -> None:
        self.helpers = _load_service_helpers()

    def test_weather_result_number_max_allows_all_options_flow_results(self) -> None:
        self.assertEqual(self.helpers.WEATHER_RESULT_NUMBER_MAX, 50)

    def test_services_yaml_uses_weather_result_number_max(self) -> None:
        text = SERVICES_YAML.read_text(encoding="utf-8")

        self.assertEqual(
            _result_number_max_values(text),
            [
                self.helpers.WEATHER_RESULT_NUMBER_MAX,
                self.helpers.WEATHER_RESULT_NUMBER_MAX,
            ],
        )


if __name__ == "__main__":
    unittest.main()
