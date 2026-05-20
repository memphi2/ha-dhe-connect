"""Tests for pure connection input helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONNECTION_HELPERS = (
    ROOT / "custom_components" / "stiebel_dhe_connect" / "connection_helpers.py"
)


def _load_connection_helpers():
    spec = importlib.util.spec_from_file_location(
        "connection_helpers",
        CONNECTION_HELPERS,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestConnectionHelpers(unittest.TestCase):
    """Validate config/options connection normalization."""

    def setUp(self) -> None:
        self.helpers = _load_connection_helpers()

    def test_normalize_host_accepts_url_without_port(self) -> None:
        self.assertEqual(
            self.helpers.normalize_host(" http://DHE-Connect.local/ "),
            "dhe-connect.local",
        )

    def test_normalize_host_rejects_url_with_explicit_port(self) -> None:
        with self.assertRaisesRegex(ValueError, "embedded_port_not_supported"):
            self.helpers.normalize_host("http://dhe-connect.local:8443/")

    def test_normalize_host_rejects_bracketed_ipv6_url_with_port(self) -> None:
        with self.assertRaisesRegex(ValueError, "embedded_port_not_supported"):
            self.helpers.normalize_host("http://[2001:db8::1]:8443/")

    def test_normalize_host_rejects_raw_host_port(self) -> None:
        with self.assertRaisesRegex(ValueError, "embedded_port_not_supported"):
            self.helpers.normalize_host("dhe-connect.local:8443")

    def test_host_for_url_wraps_ipv6(self) -> None:
        self.assertEqual(self.helpers.host_for_url("2001:db8::1"), "[2001:db8::1]")
        self.assertEqual(self.helpers.host_for_url("dhe.local"), "dhe.local")

    def test_target_changed_compares_normalized_host_and_port(self) -> None:
        current = {"host": "DHE.local.", "port": "8443"}

        self.assertFalse(
            self.helpers.target_changed(
                current,
                "dhe.local",
                8443,
                default_port=8443,
            )
        )
        self.assertTrue(
            self.helpers.target_changed(
                current,
                "dhe.local",
                9443,
                default_port=8443,
            )
        )

    def test_target_changed_is_true_when_current_data_is_invalid(self) -> None:
        self.assertTrue(
            self.helpers.target_changed(
                {"host": "", "port": "bad"},
                "dhe.local",
                8443,
                default_port=8443,
            )
        )

    def test_target_changed_rejects_bool_port_from_current_data(self) -> None:
        self.assertTrue(
            self.helpers.target_changed(
                {"host": "dhe.local", "port": True},
                "dhe.local",
                8443,
                default_port=8443,
            )
        )

    def test_validate_port_rejects_float(self) -> None:
        with self.assertRaises(ValueError):
            self.helpers.validate_port(8443.0)

    def test_validate_port_rejects_negative_float(self) -> None:
        with self.assertRaises(ValueError):
            self.helpers.validate_port(-80.1)


if __name__ == "__main__":
    unittest.main()
