"""Tests for scripts/check_release_consistency.py."""

from __future__ import annotations

import json
from io import StringIO
from contextlib import redirect_stderr
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import check_release_consistency  # noqa: E402


def _write_release_fixture(
    root: Path,
    *,
    version: str,
    changelog_body: str,
) -> None:
    manifest = root / "custom_components" / "stiebel_dhe_connect" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"version": version}), encoding="utf-8")
    (root / "README.md").write_text(
        f"# README\n\nCurrent version: `{version}`\n", encoding="utf-8"
    )
    (root / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## v{version}\n\n{changelog_body}\n",
        encoding="utf-8",
    )


class TestCheckReleaseConsistency(unittest.TestCase):
    """Validate release consistency checks."""

    def test_passes_for_stable_release_without_prerelease_terms(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_release_fixture(root, version="2.0.1", changelog_body="Stable release.")

            with (
                patch.object(check_release_consistency, "ROOT", root),
                patch.object(
                    check_release_consistency,
                    "MANIFEST",
                    root / "custom_components" / "stiebel_dhe_connect" / "manifest.json",
                ),
                patch.object(check_release_consistency, "README", root / "README.md"),
                patch.object(check_release_consistency, "CHANGELOG", root / "CHANGELOG.md"),
            ):
                check_release_consistency.main()

    def test_rejects_prerelease_terms_for_stable_release(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_release_fixture(
                root,
                version="2.0.1",
                changelog_body="This stable release is still a beta candidate.",
            )

            with (
                patch.object(check_release_consistency, "ROOT", root),
                patch.object(
                    check_release_consistency,
                    "MANIFEST",
                    root / "custom_components" / "stiebel_dhe_connect" / "manifest.json",
                ),
                patch.object(check_release_consistency, "README", root / "README.md"),
                patch.object(check_release_consistency, "CHANGELOG", root / "CHANGELOG.md"),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit),
            ):
                check_release_consistency.main()

    def test_allows_prerelease_terms_for_prerelease_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_release_fixture(
                root,
                version="2.0.1-beta",
                changelog_body="Beta release candidate for test channel.",
            )

            with (
                patch.object(check_release_consistency, "ROOT", root),
                patch.object(
                    check_release_consistency,
                    "MANIFEST",
                    root / "custom_components" / "stiebel_dhe_connect" / "manifest.json",
                ),
                patch.object(check_release_consistency, "README", root / "README.md"),
                patch.object(check_release_consistency, "CHANGELOG", root / "CHANGELOG.md"),
            ):
                check_release_consistency.main()


if __name__ == "__main__":
    unittest.main()
