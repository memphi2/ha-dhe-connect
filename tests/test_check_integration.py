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


def _write_type_gate_fixture(root: Path, files: list[str]) -> None:
    integration = root / "custom_components" / "stiebel_dhe_connect"
    integration.mkdir(parents=True)
    for name in ("__init__.py", "client.py", "config_flow_scan_state.py"):
        (integration / name).write_text("", encoding="utf-8")
    quoted_files = "\n".join(f'    "{file}",' for file in files)
    (root / "pyproject.toml").write_text(
        "[tool.mypy]\nfiles = [\n" + quoted_files + "\n]\n",
        encoding="utf-8",
    )


class TestCheckIntegration(unittest.TestCase):
    """Validate repository guard helpers."""

    def test_github_actions_accepts_pinned_validation_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_validate_workflow(
                root,
                """
                steps:
                  - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
                  - uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405
                  - uses: hacs/action@dcb30e72781db3f207d5236b861172774ab0b485
                  - uses: home-assistant/actions/hassfest@f6f29a7ee3fa0eccadf3620a7b9ee00ab54ec03b
                  - run: python -m pip install "aiohttp>=3.13.5,<4" "pytest-homeassistant-custom-component>=0.13.332,<0.14"
                  - run: python scripts/check_deprecations.py
                """,
            )

            with patch.object(check_integration, "ROOT", root):
                check_integration.check_github_actions()

    def test_github_actions_requires_deprecation_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_validate_workflow(
                root,
                """
                steps:
                  - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
                  - uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405
                  - uses: hacs/action@dcb30e72781db3f207d5236b861172774ab0b485
                  - uses: home-assistant/actions/hassfest@f6f29a7ee3fa0eccadf3620a7b9ee00ab54ec03b
                  - run: python -m pip install "aiohttp>=3.13.5,<4" "pytest-homeassistant-custom-component>=0.13.332,<0.14"
                """,
            )

            with patch.object(check_integration, "ROOT", root), redirect_stderr(
                StringIO()
            ), self.assertRaises(SystemExit):
                check_integration.check_github_actions()

    def test_github_actions_rejects_node20_action_refs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_validate_workflow(
                root,
                """
                steps:
                  - uses: actions/checkout@v4
                  - uses: actions/setup-python@v5
                  - uses: hacs/action@dcb30e72781db3f207d5236b861172774ab0b485
                  - uses: home-assistant/actions/hassfest@f6f29a7ee3fa0eccadf3620a7b9ee00ab54ec03b
                """,
            )

            with patch.object(check_integration, "ROOT", root), redirect_stderr(
                StringIO()
            ), self.assertRaises(SystemExit):
                check_integration.check_github_actions()

    def test_github_actions_rejects_floating_validation_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_validate_workflow(
                root,
                """
                steps:
                  - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
                  - uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405
                  - uses: hacs/action@main
                  - uses: home-assistant/actions/hassfest@master
                """,
            )

            with patch.object(check_integration, "ROOT", root), redirect_stderr(
                StringIO()
            ), self.assertRaises(SystemExit):
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
                  - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
                  - uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405
                  - uses: hacs/action@main
                  - uses: hacs/action@dcb30e72781db3f207d5236b861172774ab0b485
                  - uses: home-assistant/actions/hassfest@f6f29a7ee3fa0eccadf3620a7b9ee00ab54ec03b
                """,
            )

            with patch.object(check_integration, "ROOT", root), redirect_stderr(
                StringIO()
            ), self.assertRaises(SystemExit):
                check_integration.check_github_actions()

    def test_type_gate_coverage_accepts_all_integration_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            integration = root / "custom_components" / "stiebel_dhe_connect"
            files = [
                "custom_components/stiebel_dhe_connect/__init__.py",
                "custom_components/stiebel_dhe_connect/client.py",
                "custom_components/stiebel_dhe_connect/config_flow_scan_state.py",
            ]
            _write_type_gate_fixture(root, files)

            with (
                patch.object(check_integration, "ROOT", root),
                patch.object(check_integration, "INTEGRATION", integration),
            ):
                check_integration.check_type_gate_coverage()

    def test_type_gate_coverage_rejects_missing_integration_module(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            integration = root / "custom_components" / "stiebel_dhe_connect"
            _write_type_gate_fixture(
                root,
                [
                    "custom_components/stiebel_dhe_connect/__init__.py",
                    "custom_components/stiebel_dhe_connect/client.py",
                ],
            )

            with (
                patch.object(check_integration, "ROOT", root),
                patch.object(check_integration, "INTEGRATION", integration),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit),
            ):
                check_integration.check_type_gate_coverage()

    def test_type_gate_coverage_rejects_stale_integration_module(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            integration = root / "custom_components" / "stiebel_dhe_connect"
            _write_type_gate_fixture(
                root,
                [
                    "custom_components/stiebel_dhe_connect/__init__.py",
                    "custom_components/stiebel_dhe_connect/client.py",
                    "custom_components/stiebel_dhe_connect/config_flow_scan_state.py",
                    "custom_components/stiebel_dhe_connect/deleted_module.py",
                ],
            )

            with (
                patch.object(check_integration, "ROOT", root),
                patch.object(check_integration, "INTEGRATION", integration),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit),
            ):
                check_integration.check_type_gate_coverage()


if __name__ == "__main__":
    unittest.main()
