"""Tests for the repository deprecation guard."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts import check_deprecations


class TestCheckDeprecations(unittest.TestCase):
    """Validate deprecation guard behavior on synthetic files."""

    def test_accepts_clean_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "clean.py"
            path.write_text(
                "from inspect import iscoroutinefunction\n",
                encoding="utf-8",
            )

            self.assertEqual(check_deprecations.find_deprecation_issues([path]), [])

    def test_rejects_deprecated_asyncio_helper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.py"
            path.write_text(
                "import asyncio\nasyncio.iscoroutinefunction(lambda: None)\n",
                encoding="utf-8",
            )

            issues = check_deprecations.find_deprecation_issues([path])

        self.assertEqual(len(issues), 1)
        self.assertIn("inspect.iscoroutinefunction", issues[0])

    def test_rejects_warning_suppression(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.yml"
            path.write_text(
                "run: python -m pytest --disable-warnings\n",
                encoding="utf-8",
            )

            issues = check_deprecations.find_deprecation_issues([path])

        self.assertEqual(len(issues), 1)
        self.assertIn("Do not hide pytest warnings", issues[0])


if __name__ == "__main__":
    unittest.main()
