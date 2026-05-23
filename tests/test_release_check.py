"""Tests for the release readiness helper."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import ANY, patch

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
            "[docs/legal.md](docs/legal.md)\n"
            "### Removal\n"
        ),
        encoding="utf-8",
    )
    (integration / "quality_scale.yaml").write_text(
        "rules:\n  test-coverage: done\n",
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text(
        f"## Unreleased\n\n- No changes yet.\n\n## v{version} - 2026-05-16\n",
        encoding="utf-8",
    )
    (root / "docs").mkdir()
    (root / "docs" / "protocol.md").write_text("protocol\n", encoding="utf-8")
    (root / "docs" / "entities.md").write_text("entities\n", encoding="utf-8")
    (root / "docs" / "troubleshooting.md").write_text(
        "troubleshooting\n",
        encoding="utf-8",
    )
    (root / "docs" / "legal.md").write_text("legal\n", encoding="utf-8")


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
                    "[docs/legal.md](docs/legal.md)\n"
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
                "## Unreleased\n\n- No changes yet.\n\n## v1.3.20 - 2026-05-16\n",
                encoding="utf-8",
            )

            results = release_check.check_version_files(root, "1.3.2")

        self.assertIn(
            "CHANGELOG contains ## v1.3.2",
            [result.message for result in results if not result.ok],
        )

    def test_version_files_reject_pending_unreleased_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_release_files(root, "1.3.2")
            (root / "CHANGELOG.md").write_text(
                (
                    "## Unreleased\n\n"
                    "### Fixed\n\n"
                    "- Pending fix that still needs a release section.\n\n"
                    "## v1.3.2 - 2026-05-16\n"
                ),
                encoding="utf-8",
            )

            results = release_check.check_version_files(root, "1.3.2")

        self.assertIn(
            "CHANGELOG Unreleased section has no pending release entries",
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

    def test_head_tag_check_accepts_matching_release_commit(self) -> None:
        calls: list[tuple[str, ...]] = []

        def _runner(args):
            calls.append(tuple(args))
            return release_check.CommandResult(
                args=tuple(args),
                returncode=0,
                stdout="abc123\n",
                stderr="",
            )

        result = release_check.check_head_matches_tag("1.3.2", _runner)

        self.assertTrue(result.ok)
        self.assertEqual(result.message, "HEAD matches release tag v1.3.2 (abc123)")
        self.assertEqual(
            calls,
            [
                ("git", "rev-parse", "HEAD"),
                (
                    "git",
                    "rev-parse",
                    "-q",
                    "--verify",
                    "refs/tags/v1.3.2^{commit}",
                ),
            ],
        )

    def test_head_tag_check_rejects_head_after_release_tag(self) -> None:
        def _runner(args):
            stdout = (
                "123456789abcde\n"
                if args[-1] == "HEAD"
                else "fedcba98765432\n"
            )
            return release_check.CommandResult(
                args=tuple(args),
                returncode=0,
                stdout=stdout,
                stderr="",
            )

        result = release_check.check_head_matches_tag("1.3.2", _runner)

        self.assertFalse(result.ok)
        self.assertEqual(
            result.message,
            "HEAD 123456789abc does not match release tag v1.3.2 (fedcba987654)",
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
        private_host = "192.168.50.20"
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

    def test_secret_scan_rejects_vendor_web_assets(self) -> None:
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
                    stdout="assets/ste-dhe-1.9.00.js\0",
                    stderr="",
                )

            result = release_check.scan_tracked_files_for_secrets(root, _runner)

        self.assertFalse(result.ok)
        self.assertIn("tracked vendor web asset path", result.message)

    def test_secret_scan_rejects_vendor_proprietary_license_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "note.txt").write_text(
                "ste-" + "dhe - v1.9.00\n" + "Licensed " + "proprietary\n",
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
                    stdout="note.txt\0",
                    stderr="",
                )

            result = release_check.scan_tracked_files_for_secrets(root, _runner)

        self.assertFalse(result.ok)
        self.assertIn("proprietary DHE license header", result.message)

    def test_secret_scan_rejects_tracked_generated_artifacts(self) -> None:
        cases = (
            "custom_components/stiebel_dhe_connect/__pycache__/client.pyc",
            "coverage.xml",
            "htmlcov/index.html",
            ".pytest_cache/v/cache/nodeids",
            ".ruff_cache/0.13.0/file",
            ".mypy_cache/3.12/module.meta.json",
        )
        for tracked_path in cases:
            with self.subTest(tracked_path=tracked_path):
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
                            stdout=f"{tracked_path}\0",
                            stderr="",
                        )

                    result = release_check.scan_tracked_files_for_secrets(root, _runner)

                self.assertFalse(result.ok)
                self.assertIn("tracked generated artifact path", result.message)

    def test_history_sensitive_scan_passes_when_clean(self) -> None:
        def _runner(args):
            command = tuple(args)
            if command == ("git", "rev-list", "--all"):
                return release_check.CommandResult(
                    args=command,
                    returncode=0,
                    stdout="abc123\n",
                    stderr="",
                )
            if command[0:3] == ("git", "grep", "-nE"):
                return release_check.CommandResult(
                    args=command,
                    returncode=1,
                    stdout="",
                    stderr="",
                )
            raise AssertionError(f"unexpected command: {command}")

        result = release_check.scan_git_history_for_sensitive_literals(_runner)

        self.assertTrue(result.ok)
        self.assertIn("history sensitive-marker scan passed", result.message)

    def test_history_sensitive_scan_rejects_non_anonymized_markers(self) -> None:
        sample_ip = "192.168.77.9"

        def _runner(args):
            command = tuple(args)
            if command == ("git", "rev-list", "--all"):
                return release_check.CommandResult(
                    args=command,
                    returncode=0,
                    stdout="abc123\n",
                    stderr="",
                )
            if command[0:3] == ("git", "grep", "-nE"):
                return release_check.CommandResult(
                    args=command,
                    returncode=0,
                    stdout=f"abc123:CHANGELOG.md:1:{sample_ip}\n",
                    stderr="",
                )
            raise AssertionError(f"unexpected command: {command}")

        result = release_check.scan_git_history_for_sensitive_literals(_runner)

        self.assertFalse(result.ok)
        self.assertIn("non-anonymized or proprietary markers", result.message)
        self.assertIn(sample_ip, result.message)

    def test_history_sensitive_scan_chunks_commit_arguments(self) -> None:
        chunk_size = release_check.HISTORY_GREP_REVISION_CHUNK_SIZE
        commits = [f"commit-{index}" for index in range(chunk_size + 1)]
        grep_commands: list[tuple[str, ...]] = []

        def _runner(args):
            command = tuple(args)
            if command == ("git", "rev-list", "--all"):
                return release_check.CommandResult(
                    args=command,
                    returncode=0,
                    stdout="\n".join(commits) + "\n",
                    stderr="",
                )
            if command[0:3] == ("git", "grep", "-nE"):
                grep_commands.append(command)
                return release_check.CommandResult(
                    args=command,
                    returncode=1,
                    stdout="",
                    stderr="",
                )
            raise AssertionError(f"unexpected command: {command}")

        result = release_check.scan_git_history_for_sensitive_literals(_runner)

        self.assertTrue(result.ok)
        self.assertEqual(len(grep_commands), 2)
        first_separator = grep_commands[0].index("--")
        second_separator = grep_commands[1].index("--")
        self.assertEqual(first_separator - 4, chunk_size)
        self.assertEqual(second_separator - 4, 1)

    def test_history_sensitive_scan_regex_includes_all_private_ipv4_ranges(self) -> None:
        captured_marker_expr: str | None = None

        def _runner(args):
            nonlocal captured_marker_expr
            command = tuple(args)
            if command == ("git", "rev-list", "--all"):
                return release_check.CommandResult(
                    args=command,
                    returncode=0,
                    stdout="abc123\n",
                    stderr="",
                )
            if command[0:3] == ("git", "grep", "-nE"):
                captured_marker_expr = command[3]
                return release_check.CommandResult(
                    args=command,
                    returncode=1,
                    stdout="",
                    stderr="",
                )
            raise AssertionError(f"unexpected command: {command}")

        result = release_check.scan_git_history_for_sensitive_literals(_runner)

        self.assertTrue(result.ok)
        assert captured_marker_expr is not None
        self.assertIn("10\\.", captured_marker_expr)
        self.assertIn("192\\.168", captured_marker_expr)
        self.assertIn("172\\.", captured_marker_expr)

    def test_github_hygiene_scan_rejects_non_anonymized_markers(self) -> None:
        sample_user = "demo_user42"

        def _runner(args):
            command = tuple(args)
            if command[0:2] != ("gh", "api"):
                raise AssertionError(f"unexpected command: {command}")
            self.assertEqual(command[2:4], ("--paginate", "--slurp"))
            endpoint = command[4]
            if endpoint.startswith("/repos/example/repo/pulls?state=all"):
                payload = [[{"number": 1, "body": f"--username {sample_user} used in log"}]]
            else:
                payload = []
            return release_check.CommandResult(
                args=command,
                returncode=0,
                stdout=json.dumps(payload),
                stderr="",
            )

        result = release_check.scan_github_metadata_for_sensitive_literals(
            repo_full_name="example/repo",
            runner=_runner,
        )

        self.assertFalse(result.ok)
        self.assertIn("GitHub metadata contains non-anonymized or proprietary markers", result.message)
        self.assertIn(sample_user, result.message)

    def test_github_hygiene_scan_rejects_private_ipv4_markers(self) -> None:
        sample_ip = "10.1.23.45"

        def _runner(args):
            command = tuple(args)
            if command[0:2] != ("gh", "api"):
                raise AssertionError(f"unexpected command: {command}")
            self.assertEqual(command[2:4], ("--paginate", "--slurp"))
            endpoint = command[4]
            if endpoint.startswith("/repos/example/repo/pulls?state=all"):
                payload = [[{"number": 1, "body": f"debug host {sample_ip}"}]]
            else:
                payload = []
            return release_check.CommandResult(
                args=command,
                returncode=0,
                stdout=json.dumps(payload),
                stderr="",
            )

        result = release_check.scan_github_metadata_for_sensitive_literals(
            repo_full_name="example/repo",
            runner=_runner,
        )

        self.assertFalse(result.ok)
        self.assertIn("GitHub metadata contains non-anonymized or proprietary markers", result.message)
        self.assertIn(sample_ip, result.message)

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

    def test_service_smoke_restarts_before_localhost_cleanup(self) -> None:
        commands: list[tuple[str, ...]] = []

        def _runner(command):
            commands.append(tuple(command))
            return release_check.CommandResult(
                args=tuple(command),
                returncode=0,
                stdout="",
                stderr="",
            )

        result = release_check.run_ha_service_smoke(
            config=Path("/config"),
            url="http://ha.test",
            username="user",
            password_env="HA_TEST_PASSWORD",
            runner=_runner,
        )

        self.assertTrue(result.ok)
        self.assertIn("--restart-before-localhost-cleanup", commands[0])

    def test_zeroconf_smoke_uses_real_discovery_script(self) -> None:
        commands: list[tuple[str, ...]] = []

        def _runner(command):
            commands.append(tuple(command))
            return release_check.CommandResult(
                args=tuple(command),
                returncode=0,
                stdout="",
                stderr="",
            )

        result = release_check.run_zeroconf_smoke(
            timeout=12.5,
            expected_port=9443,
            runner=_runner,
        )

        self.assertTrue(result.ok)
        self.assertEqual(
            commands,
            [
                (
                    sys.executable,
                    "scripts/zeroconf_smoke.py",
                    "--timeout",
                    "12.5",
                    "--expected-port",
                    "9443",
                )
            ],
        )

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
        self.assertIn((sys.executable, "scripts/check_coverage.py"), commands)
        self.assertIn((sys.executable, "scripts/check_deprecations.py"), commands)
        self.assertIn(
            (sys.executable, "-m", "pytest", "tests/test_diagnostics.py", "-q"),
            commands,
        )

    def test_zeroconf_smoke_flag_adds_release_gate(self) -> None:
        args = release_check._parse_args(
            [
                "--allow-dirty",
                "--expect-tag",
                "skip",
                "--expect-github-release",
                "skip",
                "--run-zeroconf-smoke",
                "--zeroconf-timeout",
                "9",
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
            patch(
                "scripts.release_check.scan_tracked_files_for_secrets",
                return_value=release_check.CheckResult(True, "secret scan ok"),
            ),
        ):
            results = release_check.collect_results(args, _runner)

        self.assertTrue(all(result.ok for result in results), results)
        self.assertIn(
            (
                sys.executable,
                "scripts/zeroconf_smoke.py",
                "--timeout",
                "9.0",
                "--expected-port",
                "8443",
            ),
            commands,
        )

    def test_github_hygiene_flag_adds_release_gate(self) -> None:
        args = release_check._parse_args(
            [
                "--allow-dirty",
                "--expect-tag",
                "skip",
                "--expect-github-release",
                "skip",
                "--run-github-hygiene",
                "--github-repo",
                "example/repo",
            ]
        )

        with (
            patch("scripts.release_check.load_manifest_version", return_value="1.3.2"),
            patch("scripts.release_check.check_version_files", return_value=[]),
            patch(
                "scripts.release_check.scan_tracked_files_for_secrets",
                return_value=release_check.CheckResult(True, "tracked-file scan ok"),
            ),
            patch(
                "scripts.release_check.scan_git_history_for_sensitive_literals",
                return_value=release_check.CheckResult(True, "history scan ok"),
            ),
            patch(
                "scripts.release_check.scan_github_metadata_for_sensitive_literals",
                return_value=release_check.CheckResult(True, "github scan ok"),
            ) as github_scan,
        ):
            results = release_check.collect_results(
                args,
                lambda command: release_check.CommandResult(
                    args=tuple(command),
                    returncode=0,
                    stdout="",
                    stderr="",
                ),
            )

        self.assertTrue(all(result.ok for result in results), results)
        github_scan.assert_called_once_with(
            repo_full_name="example/repo",
            runner=ANY,
        )

    def test_history_hygiene_flag_adds_release_gate(self) -> None:
        args = release_check._parse_args(
            [
                "--allow-dirty",
                "--expect-tag",
                "skip",
                "--expect-github-release",
                "skip",
                "--run-history-hygiene",
            ]
        )

        with (
            patch("scripts.release_check.load_manifest_version", return_value="1.3.2"),
            patch("scripts.release_check.check_version_files", return_value=[]),
            patch(
                "scripts.release_check.scan_tracked_files_for_secrets",
                return_value=release_check.CheckResult(True, "tracked-file scan ok"),
            ),
            patch(
                "scripts.release_check.scan_git_history_for_sensitive_literals",
                return_value=release_check.CheckResult(True, "history scan ok"),
            ) as history_scan,
        ):
            results = release_check.collect_results(
                args,
                lambda command: release_check.CommandResult(
                    args=tuple(command),
                    returncode=0,
                    stdout="",
                    stderr="",
                ),
            )

        self.assertTrue(all(result.ok for result in results), results)
        history_scan.assert_called_once_with(ANY)

    def test_history_hygiene_scan_is_not_enabled_by_default(self) -> None:
        args = release_check._parse_args(
            [
                "--allow-dirty",
                "--expect-tag",
                "skip",
                "--expect-github-release",
                "skip",
            ]
        )

        with (
            patch("scripts.release_check.load_manifest_version", return_value="1.3.2"),
            patch("scripts.release_check.check_version_files", return_value=[]),
            patch(
                "scripts.release_check.scan_tracked_files_for_secrets",
                return_value=release_check.CheckResult(True, "tracked-file scan ok"),
            ),
            patch(
                "scripts.release_check.scan_git_history_for_sensitive_literals",
                return_value=release_check.CheckResult(True, "history scan ok"),
            ) as history_scan,
        ):
            results = release_check.collect_results(
                args,
                lambda command: release_check.CommandResult(
                    args=tuple(command),
                    returncode=0,
                    stdout="",
                    stderr="",
                ),
            )

        self.assertTrue(all(result.ok for result in results), results)
        history_scan.assert_not_called()

    def test_require_current_tag_adds_head_tag_check(self) -> None:
        args = release_check._parse_args(["--require-current-tag"])
        commands: list[tuple[str, ...]] = []

        def _runner(command):
            commands.append(tuple(command))
            if tuple(command) == ("gh", "release", "view", "v1.3.2", "--json", "tagName,isDraft"):
                return release_check.CommandResult(
                    args=tuple(command),
                    returncode=1,
                    stdout="release not found",
                    stderr="",
                )
            return release_check.CommandResult(
                args=tuple(command),
                returncode=0,
                stdout="abc123\n",
                stderr="",
            )

        with (
            patch("scripts.release_check.load_manifest_version", return_value="1.3.2"),
            patch("scripts.release_check.check_version_files", return_value=[]),
            patch("scripts.release_check.scan_tracked_files_for_secrets", return_value=release_check.CheckResult(True, "secret scan ok")),
        ):
            results = release_check.collect_results(args, _runner)

        self.assertTrue(
            any(
                result.message == "HEAD matches release tag v1.3.2 (abc123)"
                for result in results
            )
        )
        self.assertIn(("git", "rev-parse", "HEAD"), commands)

    def test_service_smoke_defaults_to_portable_local_ha_url(self) -> None:
        args = release_check._parse_args([])

        self.assertEqual(args.ha_url, "http://127.0.0.1:8123")


if __name__ == "__main__":
    unittest.main()
