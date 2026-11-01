"""Resolve and verify a matching Home Assistant core/test-helper baseline."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from urllib.request import Request, urlopen

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parents[1]
CORE_URL = "https://github.com/home-assistant/core.git"
HELPER_SUBDIR = "packages/pytest-home-assistant"
API_URL = "https://api.github.com/repos/home-assistant/core"


@dataclass(frozen=True)
class HABaseline:
    """The core version and immutable revision of its own test helpers."""

    version: Version
    commit: str | None = None
    legacy_helpers_version: str | None = None

    def requirements(self) -> str:
        """Render an installable pair without changing repository requirements."""
        if self.legacy_helpers_version is not None:
            return (
                f"homeassistant=={self.version}\n"
                f"pytest-homeassistant-custom-component=={self.legacy_helpers_version}\n"
            )
        return (
            f"homeassistant=={self.version}\n"
            f"pytest-home-assistant @ git+{CORE_URL}@{self.commit}"
            f"#subdirectory={HELPER_SUBDIR}\n"
        )


def read_baseline(path: Path) -> HABaseline:
    """Parse the central two-package baseline using PEP 508 requirements."""
    requirements = [
        Requirement(line.strip())
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    names = {r.name for r in requirements}
    if len(requirements) != 2 or names not in (
        {"homeassistant", "pytest-home-assistant"},
        {"homeassistant", "pytest-homeassistant-custom-component"},
    ):
        raise ValueError("HA baseline must contain exactly core and its test helpers")
    core = next(r for r in requirements if r.name == "homeassistant")
    pins = list(core.specifier)
    if len(pins) != 1 or pins[0].operator != "==" or core.marker or core.url or core.extras:
        raise ValueError("Home Assistant must have one exact version pin")
    if "pytest-homeassistant-custom-component" in names:
        helpers = next(r for r in requirements if r.name == "pytest-homeassistant-custom-component")
        helper_pins = list(helpers.specifier)
        if (
            len(helper_pins) != 1 or helper_pins[0].operator != "=="
            or helpers.marker or helpers.url or helpers.extras
            or Version(helper_pins[0].version).is_prerelease
            or Version(helper_pins[0].version).is_devrelease
        ):
            raise ValueError("HA 2026.10 test helpers must have one stable exact pin")
        return HABaseline(Version(pins[0].version), legacy_helpers_version=helper_pins[0].version)
    helpers = next(r for r in requirements if r.name == "pytest-home-assistant")
    match = re.fullmatch(
        re.escape(f"git+{CORE_URL}@") + r"([0-9a-f]{40})"
        + re.escape(f"#subdirectory={HELPER_SUBDIR}"), helpers.url or "",
    )
    if match is None or helpers.marker or helpers.extras:
        raise ValueError("HA test helpers must use an immutable core Git revision")
    return HABaseline(Version(pins[0].version), match[1])


def installed_baseline_errors(baseline: HABaseline) -> list[str]:
    """Verify installed distributions, including pip's recorded VCS provenance."""
    errors = []
    try:
        installed = Version(metadata.version("homeassistant"))
        if installed != baseline.version:
            errors.append(f"installed HA {installed} does not match {baseline.version}")
    except metadata.PackageNotFoundError:
        errors.append("Home Assistant is not installed")
    if baseline.legacy_helpers_version is not None:
        try:
            helpers = metadata.distribution("pytest-homeassistant-custom-component")
            if helpers.version != baseline.legacy_helpers_version:
                errors.append("installed HA 2026.10 test helpers do not match the pinned version")
            core_requirements = [
                requirement for value in helpers.requires or []
                if (requirement := Requirement(value)).name == "homeassistant"
            ]
            if (
                len(core_requirements) != 1
                or core_requirements[0].specifier != SpecifierSet(f"=={baseline.version}")
                or core_requirements[0].marker or core_requirements[0].url
                or core_requirements[0].extras
            ):
                errors.append("HA 2026.10 test helpers do not pin the selected core version")
        except metadata.PackageNotFoundError:
            errors.append("HA 2026.10 test helpers are not installed")
        except (ValueError, TypeError):
            errors.append("HA 2026.10 test-helper metadata is invalid")
        return errors
    try:
        origin = json.loads(
            metadata.distribution("pytest-home-assistant").read_text("direct_url.json") or "{}"
        )
        if (
            origin.get("url") != CORE_URL
            or origin.get("subdirectory") != HELPER_SUBDIR
            or origin.get("vcs_info", {}).get("vcs") != "git"
            or origin.get("vcs_info", {}).get("commit_id") != baseline.commit
        ):
            errors.append("installed HA test helpers do not match the pinned core Git revision")
    except metadata.PackageNotFoundError:
        errors.append("official HA test helpers are not installed")
    except (ValueError, AttributeError, TypeError):
        errors.append("installed HA test-helper provenance is invalid")
    return errors


def fetch_json(url: str) -> dict:
    """Read release metadata without logging authentication headers."""
    headers = {"Accept": "application/json", "User-Agent": "DHE-Connect-baseline-check"}
    if url.startswith(f"{API_URL}/") and (token := os.environ.get("GH_TOKEN")):
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(url, headers=headers), timeout=30) as response:
        return json.load(response)


def resolve_core_commit(version: Version) -> str:
    """Resolve a release tag, peeling annotated tags instead of guessing a SHA."""
    obj = fetch_json(f"{API_URL}/git/ref/tags/{version}")["object"]
    for _ in range(5):
        sha = obj.get("sha", "")
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            break
        if obj.get("type") == "commit":
            return sha
        if obj.get("type") != "tag":
            break
        obj = fetch_json(f"{API_URL}/git/tags/{sha}")["object"]
    raise ValueError("HA release tag did not resolve to an immutable core commit")


def latest_baseline(current: HABaseline) -> HABaseline:
    """Prefer supported stable releases; previews never downgrade the baseline."""
    if current.legacy_helpers_version is not None:
        raise ValueError("use the primary requirements-ha.txt for latest-HA drift checks")
    releases = fetch_json("https://pypi.org/pypi/homeassistant/json")["releases"]
    candidates = []
    for value, files in releases.items():
        try:
            version = Version(value)
        except InvalidVersion:
            continue
        if files and any(not file.get("yanked", False) for file in files):
            candidates.append(version)
    stable = [v for v in candidates if not v.is_prerelease and not v.is_devrelease and v >= current.version]
    if stable:
        version = max(stable)
    elif current.version.is_prerelease:
        previews = [
            v for v in candidates if not v.is_devrelease
            and v.release[:2] == current.version.release[:2] and v >= current.version
        ]
        if not previews:
            raise ValueError("no installable HA release at or above the baseline")
        version = max(previews)
    else:
        raise ValueError("no supported stable HA release is available")
    return HABaseline(version, resolve_core_commit(version))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", type=Path, default=ROOT / "requirements-ha.txt")
    parser.add_argument("--resolve-latest", type=Path, metavar="OUTPUT")
    args = parser.parse_args(argv)
    try:
        baseline = read_baseline(args.requirements)
        if args.resolve_latest:
            target = args.resolve_latest.resolve()
            if target == args.requirements.resolve():
                raise ValueError("drift resolution must not overwrite the pinned baseline")
            latest = latest_baseline(baseline)
            target.write_text(latest.requirements(), encoding="utf-8")
            print(f"resolved HA {latest.version} with matching test helpers {latest.commit}")
            return 0
        errors = installed_baseline_errors(baseline)
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1
        print(
            f"installed HA baseline verified: {baseline.version}, "
            f"helpers {baseline.legacy_helpers_version or baseline.commit}"
        )
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"ERROR: HA baseline validation failed ({type(error).__name__})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
