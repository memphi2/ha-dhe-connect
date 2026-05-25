"""Fail when sensitive runtime credentials or private lab targets are committed."""

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
)
SCAN_FILES = {
    "CHANGELOG.md",
    "README.md",
    "SECURITY.md",
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
    "scripts/check_privacy_markers.py",
    "tests/test_check_privacy_markers.py",
}


@dataclass(frozen=True)
class PrivacyPattern:
    """One privacy marker that must never be committed."""

    regex: re.Pattern[str]
    message: str


PRIVACY_PATTERNS = (
    PrivacyPattern(
        re.compile(
            r"\bHA_TEST_USERNAME\s*=\s*"
            r"(?!['\"]?your-ha-user['\"]?(?:\s|#|$))[^\s#]+"
        ),
        "Remove non-placeholder HA_TEST_USERNAME from tracked files.",
    ),
    PrivacyPattern(
        re.compile(
            r"\bHA_TEST_PASSWORD\s*=\s*"
            r"(?!['\"]?your-ha-password['\"]?(?:\s|#|$))[^\s#]+"
        ),
        "Remove non-placeholder HA_TEST_PASSWORD from tracked files.",
    ),
    PrivacyPattern(
        re.compile(
            r"\bHA_TEST_URL\s*=\s*https?://"
            r"(?:10[.]\d{1,3}[.]\d{1,3}[.]\d{1,3}"
            r"|172[.](?:1[6-9]|2\d|3[01])[.]\d{1,3}[.]\d{1,3}"
            r"|192[.]168[.]\d{1,3}[.]\d{1,3})"
            r"(?::\d+)?\b"
        ),
        "Remove private-IP HA_TEST_URL from tracked files.",
    ),
    PrivacyPattern(
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{8,}[.][A-Za-z0-9_-]{8,}[.][A-Za-z0-9_-]{8,}\b"
        ),
        "Remove JWT-like token value; keep secrets in env vars only.",
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


def find_privacy_issues(paths: list[Path]) -> list[str]:
    """Return privacy-marker guard failures for tracked repository files."""
    issues: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        try:
            relative = path.relative_to(ROOT)
        except ValueError:
            relative = path
        for pattern in PRIVACY_PATTERNS:
            for match in pattern.regex.finditer(text):
                issues.append(
                    f"{relative}:{_line_number(text, match.start())}: "
                    f"{pattern.message}"
                )
    return issues


def main() -> int:
    issues = find_privacy_issues(_tracked_files())
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}", file=sys.stderr)
        return 1
    print("privacy marker guard ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
