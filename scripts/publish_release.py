"""Publish only a validated tag, verifying draft assets before making it public."""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

try:
    from scripts import audit_github_public_surfaces as audit
    from scripts import build_release as build
    from scripts import release_check as checks
except ModuleNotFoundError:
    import audit_github_public_surfaces as audit
    import build_release as build
    import release_check as checks

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = build.REPOSITORY


def release_notes(changelog: str, tag: str) -> str:
    """Require dated, non-placeholder notes for the exact stable version."""
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError("release tag must be a stable vX.Y.Z version")
    heading = re.search(
        rf"^## {re.escape(tag)} - (\d{{4}}-\d{{2}}-\d{{2}})$", changelog, re.MULTILINE,
    )
    if heading is None or date.fromisoformat(heading[1]) > datetime.now(UTC).date():
        raise ValueError("release notes need a valid publication date, not Unreleased or a future date")
    following = re.search(r"^##\s+", changelog[heading.end():], re.MULTILINE)
    end = heading.end() + following.start() if following else len(changelog)
    notes = changelog[heading.end():end].strip()
    if not notes or notes == "- No changes yet.":
        raise ValueError("release notes must describe the published changes")
    return notes


def _runner(args):
    return checks.run_command([
        arg.replace("repos/{owner}/{repo}", f"repos/{REPOSITORY}") for arg in args
    ])


def _command(*args: str) -> None:
    result = _runner(["gh", "release", *args, "--repo", REPOSITORY])
    if result.returncode:
        # CLI errors may contain server responses; do not publish them in CI logs.
        raise ValueError(f"GitHub release {args[0]} failed; any draft remains unpublished")


def _find_release(tag: str) -> dict | None:
    matches = [item for item in audit._items(
        f"repos/{REPOSITORY}/releases?per_page=100", _runner,
    ) if item.get("tag_name") == tag]
    if len(matches) > 1:
        raise ValueError("multiple releases refer to the requested tag")
    return matches[0] if matches else None


def _verify_remote_tag(tag: str) -> None:
    if not checks.check_github_tag_matches_head(tag[1:], _runner).ok:
        raise ValueError("remote release tag does not verifiably match HEAD")


def verify_release(release: dict, tag: str, notes: str, assets: dict[str, bytes]) -> set[str]:
    """Verify metadata and every existing asset; return only genuinely missing names."""
    if (
        release.get("tag_name") != tag
        or release.get("name") != tag
        or not isinstance(release.get("body"), str)
        or release["body"].strip() != notes
        or release.get("prerelease") is not False
        or type(release.get("draft")) is not bool
        or (not release["draft"] and (
            not isinstance(release.get("published_at"), str) or not release["published_at"].strip()
        ))
    ):
        raise ValueError("existing release metadata differs from the intended stable release")
    release_id = audit._identifier(release)
    seen = set()
    for asset in audit._items(f"repos/{REPOSITORY}/releases/{release_id}/assets?per_page=100", _runner):
        name = asset.get("name")
        if name not in assets or name in seen or asset.get("state") != "uploaded":
            raise ValueError("release contains unexpected, duplicate or incomplete assets")
        if audit.download_asset(REPOSITORY, audit._identifier(asset)) != assets[name]:
            raise ValueError("downloaded release asset differs from committed source")
        seen.add(name)
    missing = assets.keys() - seen
    if missing and not release["draft"]:
        raise ValueError("published release is missing assets; refusing to modify it")
    return missing


def publish(tag: str) -> None:
    notes = release_notes((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), tag)
    if tag != f"v{checks.load_manifest_version(ROOT)}":
        raise ValueError("release tag does not match the integration manifest")
    if checks.main([
        "--expect-tag", "present", "--require-current-tag", "--expect-github-release", "skip",
    ]):
        raise ValueError("release preflight failed; no release was changed")
    assets = build.build_assets(ROOT)
    _verify_remote_tag(tag)
    release = _find_release(tag)
    if release is not None:
        missing = verify_release(release, tag, notes, assets)
        if not release["draft"]:
            _verify_remote_tag(tag)
            print("Published release already matches committed source; nothing changed")
            return
    else:
        missing = set(assets)
    with tempfile.TemporaryDirectory(prefix="dhe-release-") as directory:
        output = Path(directory)
        for name, data in assets.items():
            (output / name).write_bytes(data)
        build.verify_assets(output, assets)
        notes_file = output / "release-notes.md"
        notes_file.write_text(notes + "\n", encoding="utf-8")
        if release is None:
            _command("create", tag, "--draft", "--verify-tag", "--title", tag,
                     "--notes-file", str(notes_file))
        if missing:
            _command("upload", tag, *(str(output / name) for name in sorted(missing)))
        release = _find_release(tag)
        if release is None or not release.get("draft") or verify_release(release, tag, notes, assets):
            raise ValueError("draft verification failed; refusing publication")
        _verify_remote_tag(tag)
        _command("edit", tag, "--draft=false")
    release = _find_release(tag)
    if release is None or release.get("draft") or verify_release(release, tag, notes, assets):
        raise ValueError("published release verification failed")
    _verify_remote_tag(tag)
    print("Published release metadata and all four downloaded assets match committed source")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args(argv)
    try:
        publish(args.tag)
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"ERROR: release publication stopped ({type(error).__name__}): {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
