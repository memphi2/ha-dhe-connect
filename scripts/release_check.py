"""Release readiness checks for the DHE Connect repository."""

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
CHANGELOG_HEADING_RE = re.compile(r"^##\s+", re.MULTILINE)
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
GENERATED_ARTIFACT_PATH_PATTERNS = (
    re.compile(r"(^|/)__pycache__/"),
    re.compile(r"\.py[co]$"),
    re.compile(r"(^|/)\.coverage$"),
    re.compile(r"(^|/)coverage\.xml$"),
    re.compile(r"(^|/)htmlcov(?:/|$)"),
    re.compile(r"(^|/)\.(?:mypy|pytest|ruff)_cache(?:/|$)"),
)
VENDOR_WEB_ASSET_PATH_PATTERNS = (
    re.compile(r"(^|/)dhe-js-check(?:/|$)", re.IGNORECASE),
    re.compile(r"(^|/)ste-dhe-[^/]*\.(?:js|css|map|html)$", re.IGNORECASE),
    re.compile(r"(^|/)assets/ste-dhe-[^/]*\.(?:js|css|map|html)$", re.IGNORECASE),
)
PROPRIETARY_VENDOR_CONTENT_PATTERNS = (
    (
        "proprietary DHE license header",
        re.compile(
            rb"ste-dhe\s*-\s*v[0-9].{0,80}"
            + b"Licensed "
            + b"proprietary",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "proprietary license marker",
        re.compile(b"Licensed " + b"proprietary", re.IGNORECASE),
    ),
    (
        "vendor copyright ownership text",
        re.compile(b"This software " + b"is copyrighted", re.IGNORECASE),
    ),
    (
        "vendor legal entity copyright block",
        re.compile(
            bytes.fromhex("5354494542454c20454c54524f4e")
            + rb"\s+GmbH\s*&\s*Co\.?\s*KG",
            re.IGNORECASE,
        ),
    ),
    (
        "vendor redistribution prohibition",
        re.compile(
            b"unauthorized use, "
            + b"duplication, transmission, distribution",
            re.IGNORECASE,
        ),
    ),
    (
        "copied DHE web-template marker",
        re.compile(
            b"temperature/tpl/" + b"display" + rb"\.tpl\.html|display" + b"Wrench",
            re.IGNORECASE,
        ),
    ),
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
            _changelog_unreleased_is_empty(changelog),
            "CHANGELOG Unreleased section has no pending release entries",
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
    troubleshooting = root / "docs" / "troubleshooting.md"
    results.append(
        CheckResult(
            troubleshooting.exists()
            and "[docs/troubleshooting.md](docs/troubleshooting.md)" in readme,
            "README troubleshooting reference points to docs/troubleshooting.md",
        )
    )
    legal = root / "docs" / "legal.md"
    results.append(
        CheckResult(
            legal.exists() and "[docs/legal.md](docs/legal.md)" in readme,
            "README legal reference points to docs/legal.md",
        )
    )
    quality_scale = root / "custom_components" / "stiebel_dhe_connect" / "quality_scale.yaml"
    results.append(
        CheckResult(
            quality_scale.exists(),
            "integration quality_scale.yaml is present",
        )
    )
    results.append(
        CheckResult(
            "### Removal" in readme,
            "README includes removal instructions",
        )
    )
    return results


def _changelog_unreleased_is_empty(changelog: str) -> bool:
    """Return whether the Unreleased section is ready for a published release."""
    section = _changelog_section(changelog, "## Unreleased")
    if section is None:
        return False
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    return not lines or lines == ["- No changes yet."]


def _changelog_section(changelog: str, heading: str) -> str | None:
    """Return the body for a top-level changelog section."""
    heading_match = re.search(rf"^{re.escape(heading)}\s*$", changelog, re.MULTILINE)
    if heading_match is None:
        return None
    next_heading = CHANGELOG_HEADING_RE.search(changelog, heading_match.end())
    end = next_heading.start() if next_heading is not None else len(changelog)
    return changelog[heading_match.end() : end]


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


def check_head_matches_tag(version: str, runner: Runner) -> CheckResult:
    """Check that the current commit is exactly the release tag commit."""
    tag = f"{TAG_PREFIX}{version}"
    head = runner(["git", "rev-parse", "HEAD"])
    if head.returncode != 0:
        return CheckResult(False, _command_failed_message(head))
    tag_commit = runner(
        ["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}"]
    )
    if tag_commit.returncode != 0:
        return CheckResult(False, _command_failed_message(tag_commit))
    head_sha = head.stdout.strip()
    tag_sha = tag_commit.stdout.strip()
    if head_sha == tag_sha:
        return CheckResult(True, f"HEAD matches release tag {tag} ({head_sha[:12]})")
    return CheckResult(
        False,
        f"HEAD {head_sha[:12]} does not match release tag {tag} ({tag_sha[:12]})",
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
        if any(pattern.search(normalized) for pattern in GENERATED_ARTIFACT_PATH_PATTERNS):
            failures.append(f"tracked generated artifact path: {relative}")
            continue
        if any(pattern.search(normalized) for pattern in VENDOR_WEB_ASSET_PATH_PATTERNS):
            failures.append(f"tracked vendor web asset path: {relative}")
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
        for label, pattern in PROPRIETARY_VENDOR_CONTENT_PATTERNS:
            if pattern.search(data):
                failures.append(f"{relative}: possible {label}")
                break

    if failures:
        return CheckResult(False, "secret scan failed:\n" + "\n".join(failures))
    return CheckResult(True, "tracked-file secret/legal scan passed")


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
        "--restart-before-localhost-cleanup",
    ]
    return check_command(args, runner)


def run_zeroconf_smoke(
    *,
    timeout: float,
    expected_port: int,
    runner: Runner,
) -> CheckResult:
    """Run the real Zeroconf/mDNS release smoke gate."""
    args = [
        sys.executable,
        "scripts/zeroconf_smoke.py",
        "--timeout",
        str(timeout),
        "--expected-port",
        str(expected_port),
    ]
    return check_command(args, runner)


def _command_failed_message(result: CommandResult) -> str:
    command = redact_sensitive_text(" ".join(result.args))
    detail = redact_sensitive_text((result.stderr or result.stdout or "").strip())
    if len(detail) > 1000:
        detail = detail[-1000:]
    return f"{command} failed with exit code {result.returncode}: {detail}"


def _result_line(result: CheckResult) -> str:
    """Return one sanitized release-check result line."""
    prefix = "PASS" if result.ok else "FAIL"
    return f"{prefix}: {redact_sensitive_text(result.message)}"


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
        "--require-current-tag",
        action="store_true",
        help="Fail unless HEAD resolves to v<version>; use after publishing a release.",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Do not fail when the git worktree has uncommitted changes.",
    )
    parser.add_argument(
        "--run-local-checks",
        action="store_true",
        help=(
            "Run pytest with coverage, integration, type and Ruff checks in "
            "addition to static checks."
        ),
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
    parser.add_argument(
        "--run-zeroconf-smoke",
        action="store_true",
        help=(
            "Run the opt-in real-network Zeroconf/mDNS release-lab smoke gate "
            "for _ste-dhe._tcp.local."
        ),
    )
    parser.add_argument(
        "--zeroconf-timeout",
        type=float,
        default=20.0,
        help="Timeout in seconds for the real Zeroconf/mDNS smoke gate.",
    )
    parser.add_argument(
        "--zeroconf-expected-port",
        type=int,
        default=8443,
        help="Expected DHE Zeroconf service port.",
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
    if args.require_current_tag:
        results.append(check_head_matches_tag(version, runner))

    if args.run_local_checks:
        results.extend(
            (
                check_command(
                    [sys.executable, "-m", "pytest", "tests/test_diagnostics.py", "-q"],
                    runner,
                ),
                check_command([sys.executable, "scripts/check_coverage.py"], runner),
                check_command([sys.executable, "scripts/check_integration.py"], runner),
                check_command([sys.executable, "scripts/check_typing.py"], runner),
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

    if args.run_zeroconf_smoke:
        results.append(
            run_zeroconf_smoke(
                timeout=args.zeroconf_timeout,
                expected_port=args.zeroconf_expected_port,
                runner=runner,
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
        print(_result_line(result))
        failed = failed or not result.ok
    if failed:
        return 1
    print("release check ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
