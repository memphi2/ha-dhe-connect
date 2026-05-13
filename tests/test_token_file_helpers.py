"""Tests for DHE token file path helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOKEN_FILE_HELPERS = (
    ROOT / "custom_components" / "stiebel_dhe_connect" / "token_file_helpers.py"
)


def _load_token_file_helpers():
    spec = importlib.util.spec_from_file_location(
        "token_file_helpers",
        TOKEN_FILE_HELPERS,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestTokenFileHelpers(unittest.TestCase):
    """Validate stable and legacy token file paths."""

    def setUp(self) -> None:
        self.helpers = _load_token_file_helpers()

    def test_token_file_for_target_uses_host_and_port(self) -> None:
        self.assertEqual(
            self.helpers.token_file_for_target("192.0.2.10", 8443),
            ".storage/stiebel_dhe_connect_token_192.0.2.10_8443.txt",
        )

    def test_legacy_token_file_for_entry_uses_entry_id(self) -> None:
        self.assertEqual(
            self.helpers.legacy_token_file_for_entry("abc123"),
            ".storage/stiebel_dhe_connect_token_abc123.txt",
        )

    def test_legacy_token_files_for_target_includes_unbounded_old_path(self) -> None:
        long_host = "device-" + ("x" * 150)

        legacy_paths = self.helpers.legacy_token_files_for_target(long_host, 8443)

        self.assertEqual(len(legacy_paths), 1)
        self.assertTrue(
            legacy_paths[0].startswith(".storage/stiebel_dhe_connect_token_device-")
        )
        self.assertNotEqual(
            legacy_paths[0],
            self.helpers.token_file_for_target(long_host, 8443),
        )

    def test_legacy_token_files_for_target_skips_current_path_duplicate(self) -> None:
        self.assertEqual(
            self.helpers.legacy_token_files_for_target("192.0.2.10", 8443),
            (),
        )


if __name__ == "__main__":
    unittest.main()
