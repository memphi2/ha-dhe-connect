"""Tests for lightweight repository checks."""

from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import check_integration  # noqa: E402


def _write_validate_workflow(root: Path, content: str) -> None:
    path = root / ".github" / "workflows" / "validate.yml"
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")


class TestCheckIntegration(unittest.TestCase):
    """Validate repository guard helpers."""

    def test_github_actions_accepts_pinned_validation_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_validate_workflow(
                root,
                """
                steps:
                  - uses: hacs/action@dcb30e72781db3f207d5236b861172774ab0b485
                  - uses: home-assistant/actions/hassfest@f6f29a7ee3fa0eccadf3620a7b9ee00ab54ec03b
                """,
            )

            with patch.object(check_integration, "ROOT", root):
                check_integration.check_github_actions()

    def test_github_actions_rejects_floating_validation_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_validate_workflow(
                root,
                """
                steps:
                  - uses: hacs/action@main
                  - uses: home-assistant/actions/hassfest@master
                """,
            )

            with patch.object(check_integration, "ROOT", root):
                with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                    check_integration.check_github_actions()

    def test_github_actions_rejects_duplicate_action_with_one_floating_ref(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_validate_workflow(
                root,
                """
                steps:
                  - uses: hacs/action@main
                  - uses: hacs/action@dcb30e72781db3f207d5236b861172774ab0b485
                  - uses: home-assistant/actions/hassfest@f6f29a7ee3fa0eccadf3620a7b9ee00ab54ec03b
                """,
            )

            with patch.object(check_integration, "ROOT", root):
                with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                    check_integration.check_github_actions()


if __name__ == "__main__":
    unittest.main()
