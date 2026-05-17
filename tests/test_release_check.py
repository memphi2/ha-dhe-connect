"""Tests for the release readiness helper."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import release_check  # noqa: E402


def _write_release_files(root: Path, version: str) -> None:
    integration = root / "custom_components" / "stiebel_dhe_connect"
    integration.mkdir(parents=True)
    (integration / "manifest.json").write_text(
        json.dumps({"version": version}),
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        (
            f"Current version: `{version}`\n"
            "[docs/protocol.md](docs/protocol.md)\n"
            "[docs/entities.md](docs/entities.md)\n"
            "[docs/troubleshooting.md](docs/troubleshooting.md)\n"
        ),
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text(
        f"## v{version} - 2026-05-16\n",
        encoding="utf-8",
    )
    (root / "docs").mkdir()
    (root / "docs" / "protocol.md").write_text("protocol\n", encoding="utf-8")
    (root / "docs" / "entities.md").write_text("entities\n", encoding="utf-8")
    (root / "docs" / "troubleshooting.md").write_text(
        "troubleshooting\n",
        encoding="utf-8",
    )


class TestReleaseCheck(unittest.TestCase):
    """Validate release-check behavior without running external commands."""

    def test_version_files_accept_matching_release_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_release_files(root, "1.3.2")

            version = release_check.load_manifest_version(root)
            results = release_check.check_version_files(root, version)

        self.assertEqual(version, "1.3.2")
        self.assertTrue(all(result.ok for result in results), results)

    def test_version_files_reject_mismatched_readme(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_release_files(root, "1.3.2")
            (root / "README.md").write_text(
                "Current version: `1.3.1`\n",
                encoding="utf-8",
            )

            results = release_check.check_version_files(root, "1.3.2")

        self.assertIn(
            "README current version matches 1.3.2",
            [result.message for result in results if not result.ok],
        )

    def test_version_files_reject_manifest_override_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_release_files(root, "1.3.1")
            (root / "README.md").write_text(
                (
                    "Current version: `1.3.2`\n"
                    "[docs/protocol.md](docs/protocol.md)\n"
                    "[docs/entities.md](docs/entities.md)\n"
                    "[docs/troubleshooting.md](docs/troubleshooting.md)\n"
                ),
                encoding="utf-8",
            )
            (root / "CHANGELOG.md").write_text(
                "## v1.3.2 - 2026-05-16\n",
                encoding="utf-8",
            )

            results = release_check.check_version_files(root, "1.3.2")

        self.assertIn(
            "manifest version matches 1.3.2",
            [result.message for result in results if not result.ok],
        )

    def test_version_files_require_exact_changelog_heading(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_release_files(root, "1.3.2")
            (root / "CHANGELOG.md").write_text(
                "## v1.3.20 - 2026-05-16\n",
                encoding="utf-8",
            )

            results = release_check.check_version_files(root, "1.3.2")

        self.assertIn(
            "CHANGELOG contains ## v1.3.2",
            [result.message for result in results if not result.ok],
        )

    def test_clean_tree_includes_untracked_files(self) -> None:
        calls: list[tuple[str, ...]] = []

        def _runner(args):
            calls.append(tuple(args))
            return release_check.CommandResult(
                args=tuple(args),
                returncode=0,
                stdout="",
                stderr="",
            )

        result = release_check.check_clean_tree(_runner)

        self.assertTrue(result.ok)
        self.assertEqual(calls, [("git", "status", "--porcelain", "-uall")])

    def test_diff_whitespace_checks_current_commit(self) -> None:
        calls: list[tuple[str, ...]] = []

        def _runner(args):
            calls.append(tuple(args))
            return release_check.CommandResult(
                args=tuple(args),
                returncode=0,
                stdout="",
                stderr="",
            )

        result = release_check.check_diff_whitespace(_runner)

        self.assertTrue(result.ok)
        self.assertEqual(
            calls,
            [("git", "diff-tree", "--check", "--no-commit-id", "--root", "-r", "-m", "HEAD")],
        )

    def test_tag_expectation_checks_use_release_tag_prefix(self) -> None:
        calls: list[tuple[str, ...]] = []

        def _runner(args):
            calls.append(tuple(args))
            return release_check.CommandResult(
                args=tuple(args),
                returncode=0,
                stdout="tag-sha\n",
                stderr="",
            )

        present = release_check.check_tag("1.3.2", "present", _runner)
        absent = release_check.check_tag("1.3.2", "absent", _runner)

        self.assertTrue(present.ok)
        self.assertFalse(absent.ok)
        self.assertEqual(
            calls[0],
            ("git", "rev-parse", "-q", "--verify", "refs/tags/v1.3.2"),
        )

    def test_github_release_absent_accepts_only_not_found_response(self) -> None:
        def _runner(args):
            self.assertEqual(
                tuple(args),
                ("gh", "release", "view", "v1.3.2", "--json", "tagName,isDraft"),
            )
            return release_check.CommandResult(
                args=tuple(args),
                returncode=1,
                stdout="release not found\n",
                stderr="",
            )

        result = release_check.check_github_release("1.3.2", "absent", _runner)

        self.assertTrue(result.ok)

    def test_github_release_absent_rejects_unverified_lookup_failure(self) -> None:
        def _runner(args):
            return release_check.CommandResult(
                args=tuple(args),
                returncode=1,
                stdout="",
                stderr="authentication required",
            )

        result = release_check.check_github_release("1.3.2", "absent", _runner)

        self.assertFalse(result.ok)
        self.assertIn("authentication required", result.message)

    def test_github_release_present_requires_release_json(self) -> None:
        def _runner(args):
            return release_check.CommandResult(
                args=tuple(args),
                returncode=0,
                stdout='{"tagName":"v1.3.2","isDraft":false}',
                stderr="",
            )

        result = release_check.check_github_release("1.3.2", "present", _runner)

        self.assertTrue(result.ok)

    def test_run_command_reports_missing_executable_without_traceback(self) -> None:
        with patch(
            "scripts.release_check.subprocess.run",
            side_effect=FileNotFoundError("missing executable"),
        ):
            result = release_check.run_command(["missing-cli", "--version"])

        self.assertEqual(result.returncode, 127)
        self.assertEqual(result.args, ("missing-cli", "--version"))
        self.assertIn("missing executable", result.stderr)

    def test_command_failed_message_redacts_auth_context(self) -> None:
        private_host = ".".join(("172", "16", "1", "147"))
        result = release_check.CommandResult(
            args=(
                "python",
                "scripts/ha_test_api.py",
                "--url",
                f"http://{private_host}:8123/?token=abc123",
                "--password",
                "secret",
            ),
            returncode=1,
            stdout="",
            stderr=(
                "access_token=def456 Authorization: Bearer ghijk "
                f"password=secret http://user:secret@{private_host}:8123"
            ),
        )

        message = release_check._command_failed_message(result)

        self.assertIn("<redacted>", message)
        self.assertIn("<private-host>", message)
        self.assertNotIn("abc123", message)
        self.assertNotIn("def456", message)
        self.assertNotIn("ghijk", message)
        self.assertNotIn("secret", message)
        self.assertNotIn(private_host, message)

    def test_result_line_redacts_auth_context(self) -> None:
        private_host = ".".join(("192", "168", "0", "20"))
        result = release_check.CheckResult(
            False,
            (
                f"http://user:secret@{private_host}:8123/?token=abc123 "
                "authorization secret"
            ),
        )

        line = release_check._result_line(result)

        self.assertEqual(line.count("<redacted>"), 3)
        self.assertIn("<private-host>", line)
        self.assertNotIn("abc123", line)
        self.assertNotIn("secret", line)
        self.assertNotIn(private_host, line)

    def test_main_prints_redacted_result_messages(self) -> None:
        private_host = ".".join(("10", "0", "0", "5"))
        result = release_check.CheckResult(
            False,
            (
                f"failed against http://{private_host}:8123/?token=abc123 "
                "access_token def456"
            ),
        )
        output = StringIO()

        with (
            patch("scripts.release_check.collect_results", return_value=[result]),
            redirect_stdout(output),
        ):
            exit_code = release_check.main([])

        printed = output.getvalue()
        self.assertEqual(exit_code, 1)
        self.assertIn("<private-host>", printed)
        self.assertIn("<redacted>", printed)
        self.assertNotIn("abc123", printed)
        self.assertNotIn("def456", printed)
        self.assertNotIn(private_host, printed)

    def test_main_preserves_exit_code_diagnostics(self) -> None:
        result = release_check.CheckResult(
            False,
            "python failed with exit code 1",
        )
        output = StringIO()

        with (
            patch("scripts.release_check.collect_results", return_value=[result]),
            redirect_stdout(output),
        ):
            exit_code = release_check.main([])

        self.assertEqual(exit_code, 1)
        self.assertIn("exit code 1", output.getvalue())

    def test_secret_scan_rejects_tracked_token_storage_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            def _runner(args):
                self.assertEqual(
                    tuple(args),
                    ("git", "ls-files", "-z", "--cached"),
                )
                return release_check.CommandResult(
                    args=tuple(args),
                    returncode=0,
                    stdout=".storage/stiebel_dhe_connect_token_host_8443.txt\0",
                    stderr="",
                )

            result = release_check.scan_tracked_files_for_secrets(root, _runner)

        self.assertFalse(result.ok)
        self.assertIn("tracked secret-like path", result.message)

    def test_secret_scan_rejects_literal_ha_password(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "script.sh").write_text(
                "HA_TEST_" "PASSWORD='very-secret-value'\n",
                encoding="utf-8",
            )

            def _runner(args):
                self.assertEqual(
                    tuple(args),
                    ("git", "ls-files", "-z", "--cached"),
                )
                return release_check.CommandResult(
                    args=tuple(args),
                    returncode=0,
                    stdout="script.sh\0",
                    stderr="",
                )

            result = release_check.scan_tracked_files_for_secrets(root, _runner)

        self.assertFalse(result.ok)
        self.assertIn("literal HA test password", result.message)

    def test_service_smoke_requires_config_and_username(self) -> None:
        args = release_check._parse_args(["--run-ha-service-smoke"])

        results = release_check.collect_results(
            args,
            lambda command: release_check.CommandResult(
                args=tuple(command),
                returncode=0,
                stdout="",
                stderr="",
            ),
        )

        failures = [result.message for result in results if not result.ok]
        self.assertIn("--ha-username is required for service smoke", failures)

    def test_local_checks_include_type_gate(self) -> None:
        args = release_check._parse_args(
            [
                "--allow-dirty",
                "--expect-tag",
                "skip",
                "--expect-github-release",
                "skip",
                "--run-local-checks",
            ]
        )
        commands: list[tuple[str, ...]] = []

        def _runner(command):
            commands.append(tuple(command))
            return release_check.CommandResult(
                args=tuple(command),
                returncode=0,
                stdout="",
                stderr="",
            )

        with (
            patch("scripts.release_check.load_manifest_version", return_value="1.3.2"),
            patch("scripts.release_check.check_version_files", return_value=[]),
        ):
            results = release_check.collect_results(args, _runner)

        self.assertTrue(all(result.ok for result in results), results)
        self.assertIn((sys.executable, "scripts/check_typing.py"), commands)

    def test_service_smoke_defaults_to_portable_local_ha_url(self) -> None:
        args = release_check._parse_args([])

        self.assertEqual(args.ha_url, "http://127.0.0.1:8123")


if __name__ == "__main__":
    unittest.main()
