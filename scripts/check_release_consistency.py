"""Release metadata consistency checks."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "custom_components" / "stiebel_dhe_connect" / "manifest.json"
README = ROOT / "README.md"
CHANGELOG = ROOT / "CHANGELOG.md"
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
STABLE_CHANGELOG_DISALLOWED_TERMS = (
    "beta",
    "pre-release",
    "prerelease",
    "release candidate",
    "rc ",
)


def _fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def _load_manifest_version() -> str:
    import json

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return str(manifest.get("version", "")).strip()


def _changelog_section_body(changelog: str, version: str) -> str | None:
    """Return section body for a top-level changelog version heading."""
    match = re.search(
        rf"^##[ \t]+v{re.escape(version)}(?:[ \t]+.*)?$",
        changelog,
        re.MULTILINE,
    )
    if match is None:
        return None
    next_heading = re.search(r"^##\s+", changelog[match.end() :], re.MULTILINE)
    if next_heading is None:
        return changelog[match.end() :]
    return changelog[match.end() : match.end() + next_heading.start()]


def main() -> None:
    version = _load_manifest_version()
    if not SEMVER_RE.fullmatch(version):
        _fail(f"manifest version is not semver-like: {version!r}")

    readme = README.read_text(encoding="utf-8")
    changelog = CHANGELOG.read_text(encoding="utf-8")

    if f"Current version: `{version}`" not in readme:
        _fail("README current version does not match manifest version")

    heading = f"## v{version}"
    if _changelog_section_body(changelog, version) is None:
        _fail(f"CHANGELOG is missing section for {heading}")

    if "-" not in version:
        section = _changelog_section_body(changelog, version)
        if section is None:
            _fail(f"CHANGELOG section body missing for {heading}")
        lower_section = section.lower()
        for term in STABLE_CHANGELOG_DISALLOWED_TERMS:
            if term in lower_section:
                _fail(
                    "stable CHANGELOG section contains prerelease term "
                    f"{term!r} in {heading}"
                )

    print("release consistency ok")


if __name__ == "__main__":
    main()
