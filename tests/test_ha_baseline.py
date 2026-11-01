"""Tests for paired HA dependency resolution and installed provenance checks."""

from __future__ import annotations

import json
import tempfile
import unittest
from importlib import metadata
from pathlib import Path
from unittest.mock import Mock, patch

from packaging.version import Version

from scripts import ha_baseline as baseline

COMMIT = "a" * 40


def origin() -> dict:
    return {
        "url": baseline.CORE_URL,
        "subdirectory": baseline.HELPER_SUBDIR,
        "vcs_info": {"vcs": "git", "commit_id": COMMIT},
    }


class TestHABaseline(unittest.TestCase):
    """No network, installation, or repository writes are needed in these tests."""

    def test_round_trip_and_reject_invalid_requirement_pairs(self) -> None:
        pair = baseline.HABaseline(Version("2026.11.0"), COMMIT)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requirements-ha.txt"
            path.write_text(pair.requirements(), encoding="utf-8")
            self.assertEqual(baseline.read_baseline(path), pair)
            for invalid in (
                pair.requirements().replace("==2026.11.0", ">=2026.11.0"),
                pair.requirements().replace(COMMIT, "dev"),
                pair.requirements().replace(baseline.CORE_URL, "https://example.com/core.git"),
                pair.requirements() + "pytest\n",
            ):
                with self.subTest(invalid=invalid):
                    path.write_text(invalid, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        baseline.read_baseline(path)

    def test_installed_version_and_immutable_helper_origin_must_match(self) -> None:
        pair = baseline.HABaseline(Version("2026.11.0"), COMMIT)
        distribution = Mock()
        with (
            patch.object(baseline.metadata, "version", return_value="2026.11.0"),
            patch.object(baseline.metadata, "distribution", return_value=distribution),
        ):
            distribution.read_text.return_value = json.dumps(origin())
            self.assertEqual(baseline.installed_baseline_errors(pair), [])
            for key, value in (("url", "https://example.com"), ("subdirectory", "wrong"), ("vcs_info", {"vcs": "git", "commit_id": "b" * 40})):
                with self.subTest(field=key):
                    invalid = origin()
                    invalid[key] = value
                    distribution.read_text.return_value = json.dumps(invalid)
                    self.assertTrue(baseline.installed_baseline_errors(pair))
            distribution.read_text.return_value = json.dumps(origin())
            with patch.object(baseline.metadata, "version", return_value="2026.11.0b1"):
                self.assertTrue(baseline.installed_baseline_errors(pair))
            for invalid_json in (None, "broken", "[]"):
                distribution.read_text.return_value = invalid_json
                self.assertTrue(baseline.installed_baseline_errors(pair))

    def test_missing_installed_distributions_fail_closed(self) -> None:
        pair = baseline.HABaseline(Version("2026.11.0"), COMMIT)
        with (
            patch.object(baseline.metadata, "version", side_effect=metadata.PackageNotFoundError),
            patch.object(baseline.metadata, "distribution", side_effect=metadata.PackageNotFoundError),
        ):
            self.assertEqual(len(baseline.installed_baseline_errors(pair)), 2)

    def test_annotated_release_tags_are_peeled_to_commits(self) -> None:
        with patch.object(baseline, "fetch_json", side_effect=[
            {"object": {"type": "tag", "sha": "b" * 40}},
            {"object": {"type": "commit", "sha": COMMIT}},
        ]) as fetch:
            self.assertEqual(baseline.resolve_core_commit(Version("2026.11.0")), COMMIT)
            self.assertIn("/git/tags/", fetch.call_args.args[0])
        with (
            patch.object(baseline, "fetch_json", return_value={"object": {"type": "tree", "sha": COMMIT}}),
            self.assertRaises(ValueError),
        ):
            baseline.resolve_core_commit(Version("2026.11.0"))

    def test_latest_stable_pair_is_selected_without_editing_baseline(self) -> None:
        current = baseline.HABaseline(Version("2026.11.0b1"), COMMIT)
        releases = {"releases": {
            "2026.10.4": [{"yanked": False}], "2026.11.0": [{"yanked": False}],
            "2026.11.1": [{"yanked": True}], "2026.12.0b1": [{"yanked": False}],
            "2026.12.0": [], "invalid": [{"yanked": False}],
        }}
        with (
            patch.object(baseline, "fetch_json", return_value=releases),
            patch.object(baseline, "resolve_core_commit", return_value="b" * 40) as resolve,
        ):
            selected = baseline.latest_baseline(current)
        self.assertEqual(selected.version, Version("2026.11.0"))
        self.assertEqual(selected.commit, "b" * 40)
        resolve.assert_called_once_with(selected.version)

    def test_preview_preparation_never_downgrades_to_old_stable(self) -> None:
        current = baseline.HABaseline(Version("2026.11.0b1"), COMMIT)
        with (
            patch.object(baseline, "fetch_json", return_value={"releases": {
                "2026.10.4": [{}], "2026.11.0b2": [{}], "2026.12.0.dev1": [{}],
            }}),
            patch.object(baseline, "resolve_core_commit", return_value=COMMIT),
        ):
            self.assertEqual(baseline.latest_baseline(current).version, Version("2026.11.0b2"))
        with (
            patch.object(baseline, "fetch_json", return_value={"releases": {"2026.10.4": [{}]}}),
            self.assertRaises(ValueError),
        ):
            baseline.latest_baseline(current)

    def test_resolve_command_preserves_pinned_repository_requirements(self) -> None:
        pair = baseline.HABaseline(Version("2026.11.0b1"), COMMIT)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "requirements-ha.txt"
            output = Path(directory) / "latest.txt"
            source.write_text(pair.requirements(), encoding="utf-8")
            with patch.object(baseline, "latest_baseline", return_value=pair):
                self.assertEqual(baseline.main(["--requirements", str(source), "--resolve-latest", str(output)]), 0)
            self.assertEqual(source.read_text(), pair.requirements())
            self.assertEqual(baseline.read_baseline(output), pair)
            self.assertEqual(baseline.main(["--requirements", str(source), "--resolve-latest", str(source)]), 1)


if __name__ == "__main__":
    unittest.main()
