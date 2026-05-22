"""Fail on deprecated APIs or warning suppression in repository-owned files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCAN_PREFIXES = (
    ".github/workflows/",
    "custom_components/stiebel_dhe_connect/",
    "docs/",
    "scripts/",
    "tests/",
)
SCAN_FILES = {
    "CHANGELOG.md",
    "README.md",
    "hacs.json",
    "pyproject.toml",
}
TEXT_SUFFIXES = {
    ".json",
    ".md",
    ".py",
    ".toml",
    ".yaml",
    ".yml",
}
EXCLUDED_FILES = {
    "scripts/check_deprecations.py",
    "tests/test_check_deprecations.py",
}


@dataclass(frozen=True)
class DeprecatedPattern:
    """One deprecated or warning-suppression pattern to reject."""

    regex: re.Pattern[str]
    message: str


PATTERNS = (
    DeprecatedPattern(
        re.compile(r"\basyncio[.]iscoroutinefunction\b"),
        "Use inspect.iscoroutinefunction instead of asyncio.iscoroutinefunction.",
    ),
    DeprecatedPattern(
        re.compile(r"\bdatetime[.]utcnow\s*[(]|\butcnow\s*[(]"),
        "Use timezone-aware datetime.now(UTC) instead of utcnow().",
    ),
    DeprecatedPattern(
        re.compile(r"@\s*asyncio[.]coroutine\b"),
        "Use async def instead of deprecated @asyncio.coroutine.",
    ),
    DeprecatedPattern(
        re.compile(r"\bwarnings[.](?:filterwarnings|simplefilter)\s*[(]"),
        "Do not suppress warnings; fix owned deprecations instead.",
    ),
    DeprecatedPattern(
        re.compile(r"\bpytest[.]mark[.]filterwarnings\b"),
        "Do not mark tests with warning filters; fix owned deprecations instead.",
    ),
    DeprecatedPattern(
        re.compile(r"ignore::DeprecationWarning|PYTHONWARNINGS\s*[:=].*ignore"),
        "Do not hide DeprecationWarning in test or CI configuration.",
    ),
    DeprecatedPattern(
        re.compile(r"--disable-warnings\b"),
        "Do not hide pytest warnings in CI or validation commands.",
    ),
)


def _tracked_files() -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    paths: list[Path] = []
    for raw in completed.stdout.splitlines():
        if raw in EXCLUDED_FILES:
            continue
        if raw in SCAN_FILES or raw.startswith(SCAN_PREFIXES):
            path = ROOT / raw
            if path.suffix in TEXT_SUFFIXES:
                paths.append(path)
    return paths


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def find_deprecation_issues(paths: list[Path]) -> list[str]:
    """Return deprecation guard failures for tracked repository files."""
    issues: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        try:
            relative = path.relative_to(ROOT)
        except ValueError:
            relative = path
        for pattern in PATTERNS:
            for match in pattern.regex.finditer(text):
                issues.append(
                    f"{relative}:{_line_number(text, match.start())}: "
                    f"{pattern.message}"
                )
    return issues


def main() -> int:
    issues = find_deprecation_issues(_tracked_files())
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}", file=sys.stderr)
        return 1
    print("deprecation guard ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
