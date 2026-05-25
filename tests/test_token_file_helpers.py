"""Tests for DHE token file path helpers."""

from __future__ import annotations

import importlib.util
import os
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
    """Validate deterministic token file paths."""

    def setUp(self) -> None:
        self.helpers = _load_token_file_helpers()

    def test_token_file_for_target_uses_host_and_port(self) -> None:
        self.assertEqual(
            self.helpers.token_file_for_target("192.0.2.10", 8443),
            ".storage/stiebel_dhe_connect_token_192.0.2.10_8443.txt",
        )

    def test_stale_unconfigured_token_paths_filters_storage_token_files(self) -> None:
        storage_path = str(ROOT / "config" / ".storage")
        configured_path = os.path.normcase(
            os.path.abspath(
                os.path.join(
                    storage_path,
                    "stiebel_dhe_connect_token_existing_8443.txt",
                )
            )
        )

        self.assertEqual(
            self.helpers.stale_unconfigured_token_paths(
                storage_path,
                [
                    "stiebel_dhe_connect_token_existing_8443.txt",
                    "stiebel_dhe_connect_token_stale_8443.txt",
                    "stiebel_dhe_connect_token_stale.json",
                    "unrelated.txt",
                ],
                {configured_path},
            ),
            {
                os.path.normcase(
                    os.path.abspath(
                        os.path.join(
                            storage_path,
                            "stiebel_dhe_connect_token_stale_8443.txt",
                        )
                    )
                )
            },
        )


if __name__ == "__main__":
    unittest.main()
