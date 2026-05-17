"""Release readiness checks for the Stiebel DHE Connect repository."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable, Sequence

try:
    from scripts.ha_test_redaction import redact_sensitive_text
except ModuleNotFoundError:
    from ha_test_redaction import redact_sensitive_text


ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "stiebel_dhe_connect"
MANIFEST = INTEGRATION / "manifest.json"
README = ROOT / "README.md"
CHANGELOG = ROOT / "CHANGELOG.md"

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[abrc]\d+)?$")
TAG_PREFIX = "v"
SECRET_PATTERNS = (
    (
        "private key",
        re.compile(rb"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"),
    ),
    ("github token", re.compile(rb"\bgh[opsu]_[A-Za-z0-9_]{36,}\b")),
    (
        "literal HA test password",
        re.compile(rb"HA_TEST_PASSWORD\s*=\s*['\"][^'\"\r\n]{8,}['\"]"),
    ),
    (
        "JSON access token",
        re.compile(
            rb'"(?:access_token|refresh_token)"\s*:\s*"'
            rb'[A-Za-z0-9._~+/=-]{20,}"'
        ),
    ),
)
SECRET_PATH_MARKERS = (
    "/.storage/",
    ".storage/",
    ".tmp_pairing_token",
    "stiebel_dhe_connect_token",
)


@dataclass(frozen=True)
class CommandResult:
    """Captured command result."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class CheckResult:
    """One release check result."""

    ok: bool
    message: str


Runner = Callable[[Sequence[str]], CommandResult]


def run_command(args: Sequence[str]) -> CommandResult:
    """Run a command in the repository root."""
    try:
        completed = subprocess.run(
            list(args),
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as err:
        return CommandResult(
            args=tuple(args),
            returncode=127,
            stdout="",
            stderr=str(err),
        )
    return CommandResult(
        args=tuple(args),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def load_manifest_version(root: Path) -> str:
    """Return the manifest version."""
    manifest = json.loads((root / MANIFEST.relative_to(ROOT)).read_text(encoding="utf-8"))
    return str(manifest.get("version", "")).strip()


def check_version_files(root: Path, version: str) -> list[CheckResult]:
    """Check manifest, README and changelog release version consistency."""
    results: list[CheckResult] = []
    manifest_version = load_manifest_version(root)
    if not SEMVER_RE.fullmatch(version):
        results.append(CheckResult(False, f"manifest version is not semver-like: {version!r}"))
        return results
    results.append(
        CheckResult(
            manifest_version == version,
            f"manifest version matches {version}",
        )
    )

    readme = (root / README.relative_to(ROOT)).read_text(encoding="utf-8")
    changelog = (root / CHANGELOG.relative_to(ROOT)).read_text(encoding="utf-8")
    protocol = root / "docs" / "protocol.md"

    results.append(
        CheckResult(
            f"Current version: `{version}`" in readme,
            f"README current version matches {version}",
        )
    )
    heading = f"## {TAG_PREFIX}{version}"
    heading_re = re.compile(rf"^{re.escape(heading)}(?:\s|$)", re.MULTILINE)
    results.append(
        CheckResult(
            bool(heading_re.search(changelog)),
            f"CHANGELOG contains {heading}",
        )
    )
    results.append(
        CheckResult(
            protocol.exists() and "[docs/protocol.md](docs/protocol.md)" in readme,
            "README protocol reference points to docs/protocol.md",
        )
    )
    entities = root / "docs" / "entities.md"
    results.append(
        CheckResult(
            entities.exists() and "[docs/entities.md](docs/entities.md)" in readme,
            "README entity reference points to docs/entities.md",
        )
    )
    return results


def check_clean_tree(runner: Runner) -> CheckResult:
    """Check that the git worktree is clean."""
    result = runner(["git", "status", "--porcelain", "-uall"])
    if result.returncode != 0:
        return CheckResult(False, _command_failed_message(result))
    if result.stdout.strip():
        return CheckResult(False, f"git worktree is dirty:\n{result.stdout.rstrip()}")
    return CheckResult(True, "git worktree is clean")


def check_diff_whitespace(runner: Runner) -> CheckResult:
    """Run git whitespace checks against the current commit."""
    result = runner(
        ["git", "diff-tree", "--check", "--no-commit-id", "--root", "-r", "-m", "HEAD"]
    )
    if result.returncode != 0:
        return CheckResult(False, _command_failed_message(result))
    return CheckResult(True, "git diff-tree --check HEAD passed")


def check_tag(version: str, expectation: str, runner: Runner) -> CheckResult:
    """Check whether the release tag exists or is still absent."""
    tag = f"{TAG_PREFIX}{version}"
    if expectation == "skip":
        return CheckResult(True, f"tag check skipped for {tag}")
    result = runner(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"])
    exists = result.returncode == 0
    expected = expectation == "present"
    return CheckResult(
        exists == expected,
        f"git tag {tag} is {'present' if exists else 'absent'}",
    )


def check_github_release(version: str, expectation: str, runner: Runner) -> CheckResult:
    """Check whether the GitHub release exists or is still absent."""
    tag = f"{TAG_PREFIX}{version}"
    if expectation == "skip":
        return CheckResult(True, f"GitHub release check skipped for {tag}")
    result = runner(["gh", "release", "view", tag, "--json", "tagName,isDraft"])
    exists = _gh_release_view_reports_existing(result)
    missing = _gh_release_view_reports_missing(result)
    if not exists and not missing:
        return CheckResult(False, _command_failed_message(result))
    expected = expectation == "present"
    return CheckResult(
        exists == expected,
        f"GitHub release {tag} is {'present' if exists else 'absent'}",
    )


def _gh_release_view_reports_existing(result: CommandResult) -> bool:
    """Return true when gh release view returned release JSON."""
    if result.returncode != 0:
        return False
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return False
    return bool(payload.get("tagName"))


def _gh_release_view_reports_missing(result: CommandResult) -> bool:
    """Return true only for the known gh release-not-found response."""
    output = f"{result.stdout}\n{result.stderr}".lower()
    return result.returncode != 0 and "release not found" in output


def check_command(args: Sequence[str], runner: Runner) -> CheckResult:
    """Run a release validation command."""
    result = runner(args)
    command = " ".join(args)
    if result.returncode != 0:
        return CheckResult(False, _command_failed_message(result))
    return CheckResult(True, f"{command} passed")


def scan_tracked_files_for_secrets(root: Path, runner: Runner) -> CheckResult:
    """Scan tracked repository files for obvious committed secret artifacts."""
    result = runner(["git", "ls-files", "-z", "--cached"])
    if result.returncode != 0:
        return CheckResult(False, _command_failed_message(result))

    failures: list[str] = []
    for relative in (item for item in result.stdout.split("\0") if item):
        normalized = relative.replace("\\", "/")
        if any(marker in normalized for marker in SECRET_PATH_MARKERS):
            failures.append(f"tracked secret-like path: {relative}")
            continue
        path = root / relative
        try:
            data = path.read_bytes()
        except OSError as err:
            failures.append(f"could not read tracked file {relative}: {err}")
            continue
        if b"\0" in data[:4096]:
            continue
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(data):
                failures.append(f"{relative}: possible {label}")
                break

    if failures:
        return CheckResult(False, "secret scan failed:\n" + "\n".join(failures))
    return CheckResult(True, "tracked-file secret scan passed")


def run_ha_smoke(
    config: Path,
    monitor_seconds: int,
    runner: Runner,
) -> CheckResult:
    """Run mounted Home Assistant smoke checks."""
    args = [
        sys.executable,
        "scripts/ha_test_smoke.py",
        "--config",
        str(config),
        "--include-fault-log",
    ]
    if monitor_seconds > 0:
        args.extend(["--monitor-seconds", str(monitor_seconds)])
    return check_command(args, runner)


def run_ha_service_smoke(
    *,
    config: Path,
    url: str,
    username: str,
    password_env: str,
    runner: Runner,
) -> CheckResult:
    """Run authenticated Home Assistant service smoke checks."""
    args = [
        sys.executable,
        "scripts/ha_test_api.py",
        "--config",
        str(config),
        "--url",
        url,
        "--username",
        username,
        "--password-env",
        password_env,
        "--service-smoke",
        "--cleanup-localhost-tokens",
    ]
    return check_command(args, runner)


def _command_failed_message(result: CommandResult) -> str:
    command = redact_sensitive_text(" ".join(result.args))
    detail = redact_sensitive_text((result.stderr or result.stdout or "").strip())
    if len(detail) > 1000:
        detail = detail[-1000:]
    return f"{command} failed with exit code {result.returncode}: {detail}"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check release readiness for the current repository state.",
    )
    parser.add_argument("--version", help="Release version; defaults to manifest version.")
    parser.add_argument(
        "--expect-tag",
        choices=("absent", "present", "skip"),
        default="absent",
        help="Expected state of git tag v<version>. Default: absent before publish.",
    )
    parser.add_argument(
        "--expect-github-release",
        choices=("absent", "present", "skip"),
        default="absent",
        help="Expected state of the GitHub release. Default: absent before publish.",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Do not fail when the git worktree has uncommitted changes.",
    )
    parser.add_argument(
        "--run-local-checks",
        action="store_true",
        help="Run pytest, integration checks and Ruff in addition to static checks.",
    )
    parser.add_argument(
        "--ha-config",
        type=Path,
        help="Mounted Home Assistant config path for ha_test_smoke.py.",
    )
    parser.add_argument(
        "--ha-monitor-seconds",
        type=int,
        default=0,
        help="Recorder monitor duration for mounted HA smoke checks.",
    )
    parser.add_argument(
        "--run-ha-service-smoke",
        action="store_true",
        help="Run authenticated HA service smoke through scripts/ha_test_api.py.",
    )
    parser.add_argument("--ha-url", default="http://127.0.0.1:8123")
    parser.add_argument("--ha-username", default="")
    parser.add_argument("--ha-password-env", default="HA_TEST_PASSWORD")
    return parser.parse_args(argv)


def collect_results(args: argparse.Namespace, runner: Runner) -> list[CheckResult]:
    """Collect all release check results."""
    manifest_version = load_manifest_version(ROOT)
    version = args.version or manifest_version
    results = check_version_files(ROOT, version)
    if not args.allow_dirty:
        results.append(check_clean_tree(runner))
    results.extend(
        (
            check_diff_whitespace(runner),
            check_tag(version, args.expect_tag, runner),
            check_github_release(version, args.expect_github_release, runner),
            scan_tracked_files_for_secrets(ROOT, runner),
        )
    )

    if args.run_local_checks:
        results.extend(
            (
                check_command([sys.executable, "-m", "pytest", "-q"], runner),
                check_command([sys.executable, "scripts/check_integration.py"], runner),
                check_command(
                    [
                        sys.executable,
                        "-m",
                        "ruff",
                        "check",
                        "custom_components/stiebel_dhe_connect",
                        "tests",
                        "scripts",
                    ],
                    runner,
                ),
            )
        )

    if args.ha_config is not None:
        monitor_seconds = 0 if args.run_ha_service_smoke else args.ha_monitor_seconds
        results.append(run_ha_smoke(args.ha_config, monitor_seconds, runner))

    if args.run_ha_service_smoke:
        if not args.ha_username:
            results.append(CheckResult(False, "--ha-username is required for service smoke"))
        elif args.ha_config is None:
            results.append(CheckResult(False, "--ha-config is required for service smoke"))
        else:
            results.append(
                run_ha_service_smoke(
                    config=args.ha_config,
                    url=args.ha_url,
                    username=args.ha_username,
                    password_env=args.ha_password_env,
                    runner=runner,
                )
            )
            if args.ha_monitor_seconds > 0:
                results.append(
                    run_ha_smoke(args.ha_config, args.ha_monitor_seconds, runner)
                )
    return results


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    results = collect_results(args, run_command)
    failed = False
    for result in results:
        prefix = "PASS" if result.ok else "FAIL"
        print(f"{prefix}: {result.message}")
        failed = failed or not result.ok
    if failed:
        return 1
    print("release check ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
