"""Read-only, opt-in privacy audit of GitHub text and release attachments."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import stat
import subprocess
import tempfile
import time
import zipfile
from collections.abc import Callable

try:
    from scripts import release_check as checks
    from scripts.check_privacy_markers import PRIVACY_PATTERNS
except ModuleNotFoundError:
    import release_check as checks
    from check_privacy_markers import PRIVACY_PATTERNS

MAX_ASSET_BYTES = 32 * 1024 * 1024
MAX_MEMBER_BYTES = 8 * 1024 * 1024
MAX_ZIP_MEMBERS = 4096
TEXT_FIELDS = {"title", "body", "name", "label"}
Download = Callable[[str, int], bytes]


def scan_bytes(data: bytes) -> set[str]:
    """Return categories only, never the matched private text."""
    findings = {
        label for label, pattern in (*checks.SECRET_PATTERNS, *checks.PROPRIETARY_VENDOR_CONTENT_PATTERNS)
        if pattern.search(data)
    }
    text = data.decode("utf-8", errors="replace")
    if any(pattern.regex.search(text) for pattern in PRIVACY_PATTERNS):
        findings.add("runtime credential marker")
    if any(re.search(pattern, text) for pattern in checks.HISTORY_SENSITIVE_REGEXES_PYTHON):
        findings.add("private address or username marker")
    return findings


def scan_zip(data: bytes) -> set[str]:
    """Inspect bounded ZIP members without extracting untrusted paths."""
    findings: set[str] = set()
    if len(data) > MAX_ASSET_BYTES:
        return {"asset exceeds audit size limit"}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > MAX_ZIP_MEMBERS or sum(info.file_size for info in members) > MAX_ASSET_BYTES:
                return {"ZIP exceeds audit expansion limit"}
            names: set[str] = set()
            for info in members:
                name = info.filename.replace("\\", "/")
                parts = name.removesuffix("/").split("/")
                if (
                    any(part in {"", ".", ".."} for part in parts)
                    or ":" in name
                    or stat.S_ISLNK(info.external_attr >> 16)
                    or name in names
                ):
                    findings.add("unsafe or duplicate ZIP member")
                    continue
                names.add(name)
                if any(marker in name for marker in checks.SECRET_PATH_MARKERS):
                    findings.add("secret-like ZIP path")
                if any(pattern.search(name) for pattern in checks.GENERATED_ARTIFACT_PATH_PATTERNS):
                    findings.add("generated ZIP artifact")
                if any(pattern.search(name) for pattern in checks.VENDOR_WEB_ASSET_PATH_PATTERNS):
                    findings.add("vendor web asset in ZIP")
                findings.update(scan_bytes(name.encode()))
                if info.file_size > MAX_MEMBER_BYTES:
                    findings.add("ZIP member exceeds audit size limit")
                    continue
                if not info.is_dir():
                    with archive.open(info) as stream:
                        member = stream.read(MAX_MEMBER_BYTES + 1)
                    if len(member) > MAX_MEMBER_BYTES:
                        findings.add("ZIP member exceeds audit size limit")
                    else:
                        findings.update(scan_bytes(member))
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, ValueError):
        findings.add("unreadable ZIP asset")
    return findings


def download_asset(repo: str, asset_id: int) -> bytes:
    """Download by trusted API path with bounded disk use and elapsed time."""
    with tempfile.TemporaryFile() as output:
        with subprocess.Popen(
            ["gh", "api", f"repos/{repo}/releases/assets/{asset_id}",
             "-H", "Accept: application/octet-stream"],
            stdout=output, stderr=subprocess.DEVNULL,
        ) as process:
            deadline = time.monotonic() + 60
            while process.poll() is None:
                if os.fstat(output.fileno()).st_size > MAX_ASSET_BYTES or time.monotonic() >= deadline:
                    process.kill()
                    process.wait()
                    raise ValueError("asset download exceeded audit limits")
                time.sleep(0.05)
            if process.returncode:
                raise ValueError("asset download failed")
        output.seek(0)
        data = output.read(MAX_ASSET_BYTES + 1)
    if len(data) > MAX_ASSET_BYTES:
        raise ValueError("asset download exceeded audit limits")
    return data


def _items(endpoint: str, runner: checks.Runner) -> list[dict]:
    result = runner(["gh", "api", endpoint, "--paginate"])
    if result.returncode:
        raise ValueError(f"GitHub audit request failed: {endpoint}")
    try:
        pages = checks._parse_paginated_gh_json(result.stdout)
    except json.JSONDecodeError:
        raise ValueError(f"GitHub audit received invalid JSON: {endpoint}") from None
    if not pages or any(not isinstance(page, list) for page in pages):
        raise ValueError(f"GitHub audit received an invalid collection: {endpoint}")
    items = [item for page in pages for item in page]
    if any(not isinstance(item, dict) for item in items):
        raise ValueError(f"GitHub audit received an invalid item: {endpoint}")
    return items


def _identifier(item: dict, key: str = "id") -> int:
    value = item.get(key)
    if type(value) is not int or value < 1:
        raise ValueError("GitHub audit received an invalid numeric identifier")
    return value


def audit_public_surfaces(
    repo: str, runner: checks.Runner, download: Download = download_asset,
) -> checks.CheckResult:
    """Audit all pages, review bodies and attached files; never modify GitHub."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", repo):
        return checks.CheckResult(False, "invalid GitHub repository name")
    findings: list[str] = []
    count = 0

    def collection(endpoint: str) -> list[dict]:
        nonlocal count
        items = _items(endpoint, runner)
        count += len(items)
        for index, item in enumerate(items, 1):
            categories: set[str] = set()
            for field in TEXT_FIELDS:
                if isinstance(value := item.get(field), str):
                    categories.update(scan_bytes(value.encode()))
            for category in sorted(categories):
                findings.append(f"{endpoint} item {index}: {category}")
        return items

    try:
        pulls = collection(f"repos/{repo}/pulls?state=all&per_page=100")
        collection(f"repos/{repo}/issues?state=all&per_page=100")
        collection(f"repos/{repo}/issues/comments?per_page=100")
        collection(f"repos/{repo}/pulls/comments?per_page=100")
        for pull in pulls:
            number = _identifier(pull, "number")
            collection(f"repos/{repo}/pulls/{number}/reviews?per_page=100")
        for release in collection(f"repos/{repo}/releases?per_page=100"):
            release_id = _identifier(release)
            for asset in collection(f"repos/{repo}/releases/{release_id}/assets?per_page=100"):
                asset_id = _identifier(asset)
                size = asset.get("size")
                label = f"release {release_id} asset {asset_id}"
                if type(size) is not int or not 0 <= size <= MAX_ASSET_BYTES:
                    findings.append(f"{label}: invalid or excessive asset size")
                    continue
                data = download(repo, asset_id)
                if len(data) != size:
                    findings.append(f"{label}: downloaded size differs from metadata")
                    continue
                name = asset.get("name")
                if not isinstance(name, str):
                    raise TypeError("GitHub audit received an invalid asset name")
                categories = (
                    scan_zip(data) if name.lower().endswith(".zip") or data.startswith(b"PK")
                    else scan_bytes(data)
                )
                findings.extend(f"{label}: {category}" for category in sorted(categories))
    except (OSError, TypeError, ValueError):
        return checks.CheckResult(False, "GitHub public-surface audit incomplete: API, download or payload failure")
    if findings:
        return checks.CheckResult(False, "GitHub public-surface audit findings:\n" + "\n".join(findings))
    return checks.CheckResult(True, f"GitHub public-surface audit passed ({count} items)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="memphi2/ha-dhe-connect")
    args = parser.parse_args(argv)
    result = audit_public_surfaces(args.repo, checks.run_command)
    print(result.message)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
