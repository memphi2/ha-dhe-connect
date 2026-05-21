"""Run the scoped static type-checking gate."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_PACKAGE = ROOT / "custom_components" / "stiebel_dhe_connect"
MYPY_CONFIG = ROOT / "pyproject.toml"


def _repo_path(path: Path) -> str:
    """Return a stable repository-relative POSIX path."""
    return path.relative_to(ROOT).as_posix()


def _configured_mypy_files() -> set[str]:
    """Return the module file list from pyproject.toml."""
    with MYPY_CONFIG.open("rb") as handle:
        config = tomllib.load(handle)
    configured = config.get("tool", {}).get("mypy", {}).get("files", [])
    return {str(path) for path in configured}


def _integration_modules() -> set[str]:
    """Return every top-level Python module shipped by the integration."""
    return {
        _repo_path(path)
        for path in INTEGRATION_PACKAGE.glob("*.py")
        if path.is_file()
    }


def _print_paths(title: str, paths: set[str]) -> None:
    """Print a deterministic path list for actionable typing-scope failures."""
    print(title, file=sys.stderr)
    for path in sorted(paths):
        print(f"  - {path}", file=sys.stderr)


def _check_mypy_scope() -> int:
    """Ensure strict typing cannot silently skip integration modules."""
    configured = _configured_mypy_files()
    integration_modules = _integration_modules()
    missing = integration_modules - configured
    stale = configured - integration_modules
    if not missing and not stale:
        return 0
    if missing:
        _print_paths("ERROR: mypy files is missing integration modules:", missing)
    if stale:
        _print_paths("ERROR: mypy files contains stale paths:", stale)
    return 1


def main() -> int:
    """Run mypy with repository configuration."""
    if importlib.util.find_spec("mypy") is None:
        print(
            "ERROR: mypy is not installed. Install it with "
            "`python -m pip install 'mypy>=1.13,<2'`.",
            file=sys.stderr,
        )
        return 1
    scope_result = _check_mypy_scope()
    if scope_result != 0:
        return scope_result
    return subprocess.run(
        [sys.executable, "-m", "mypy"],
        cwd=ROOT,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
