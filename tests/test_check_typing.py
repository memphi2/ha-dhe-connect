"""Tests for the direct typing-gate helper."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import check_typing  # noqa: E402


def _write_type_gate_fixture(root: Path, files: list[str]) -> Path:
    integration = root / "custom_components" / "stiebel_dhe_connect"
    integration.mkdir(parents=True)
    for name in ("__init__.py", "client.py", "config_flow.py"):
        (integration / name).write_text("", encoding="utf-8")
    quoted_files = "\n".join(f'    "{file}",' for file in files)
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        "[tool.mypy]\nfiles = [\n" + quoted_files + "\n]\n",
        encoding="utf-8",
    )
    return integration


def test_check_typing_scope_accepts_all_integration_modules() -> None:
    """Accept a mypy file list that exactly covers integration modules."""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        integration = _write_type_gate_fixture(
            root,
            [
                "custom_components/stiebel_dhe_connect/__init__.py",
                "custom_components/stiebel_dhe_connect/client.py",
                "custom_components/stiebel_dhe_connect/config_flow.py",
            ],
        )
        with (
            patch.object(check_typing, "ROOT", root),
            patch.object(check_typing, "INTEGRATION_PACKAGE", integration),
            patch.object(check_typing, "MYPY_CONFIG", root / "pyproject.toml"),
        ):
            assert check_typing._check_mypy_scope() == 0


def test_check_typing_scope_rejects_missing_integration_module() -> None:
    """Reject a mypy file list that skips an integration module."""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        integration = _write_type_gate_fixture(
            root,
            [
                "custom_components/stiebel_dhe_connect/__init__.py",
                "custom_components/stiebel_dhe_connect/client.py",
            ],
        )
        with (
            patch.object(check_typing, "ROOT", root),
            patch.object(check_typing, "INTEGRATION_PACKAGE", integration),
            patch.object(check_typing, "MYPY_CONFIG", root / "pyproject.toml"),
        ):
            assert check_typing._check_mypy_scope() == 1


def test_check_typing_scope_rejects_stale_integration_module() -> None:
    """Reject a mypy file list with stale integration paths."""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        integration = _write_type_gate_fixture(
            root,
            [
                "custom_components/stiebel_dhe_connect/__init__.py",
                "custom_components/stiebel_dhe_connect/client.py",
                "custom_components/stiebel_dhe_connect/config_flow.py",
                "custom_components/stiebel_dhe_connect/deleted.py",
            ],
        )
        with (
            patch.object(check_typing, "ROOT", root),
            patch.object(check_typing, "INTEGRATION_PACKAGE", integration),
            patch.object(check_typing, "MYPY_CONFIG", root / "pyproject.toml"),
        ):
            assert check_typing._check_mypy_scope() == 1
