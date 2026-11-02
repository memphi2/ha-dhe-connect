"""Focused asset/protocol provenance checks, not a legal opinion or clearance."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

try:
    from scripts import release_check
    from scripts.check_privacy_markers import PRIVACY_PATTERNS
except ModuleNotFoundError:
    import release_check
    from check_privacy_markers import PRIVACY_PATTERNS

ROOT = Path(__file__).resolve().parents[1]
PROVENANCE_PATH = "docs/asset_provenance.json"
COMPONENT_PREFIX = "custom_components/stiebel_dhe_connect/"
MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp", ".avif"}
FORBIDDEN_SUFFIXES = {".zip", ".7z", ".tar", ".tgz", ".gz", ".xz", ".bin", ".img", ".elf", ".so", ".apk", ".har", ".pcap", ".pcapng"}
FIXTURE_PROVENANCE = {
    "kind": "synthetic",
    "source": "docs/protocol.md",
    "license": "MIT",
    "contains_live_capture": False,
}


def parse_inventory(data: bytes) -> dict[str, dict[str, str]]:
    """Read the documented asset inventory with no inferred licensing claims."""
    def unique_pairs(pairs):
        mapping = {}
        for key, value in pairs:
            if key in mapping:
                raise ValueError("duplicate provenance key")
            mapping[key] = value
        return mapping

    payload = json.loads(data, object_pairs_hook=unique_pairs)
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("invalid asset provenance version")
    assets = payload.get("assets")
    if not isinstance(assets, dict):
        raise TypeError("invalid asset inventory")
    for path, entry in assets.items():
        if (
            not isinstance(entry, dict)
            or set(entry) != {"sha256", "origin", "rights"}
            or any(not isinstance(value, str) or not value.strip() for value in entry.values())
            or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
            or PurePosixPath(path).is_absolute()
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or "\\" in path
        ):
            raise ValueError("invalid asset provenance entry")
    return assets


def content_issues(label: str, data: bytes) -> list[str]:
    """Use existing secret/proprietary markers without printing their values."""
    findings = [
        f"{label}: possible {name}"
        for name, pattern in (
            *release_check.SECRET_PATTERNS, *release_check.PROPRIETARY_VENDOR_CONTENT_PATTERNS,
        ) if pattern.search(data)
    ]
    if any(pattern.regex.search(data.decode("utf-8", errors="replace")) for pattern in PRIVACY_PATTERNS):
        findings.append(f"{label}: private runtime credential marker")
    return findings


def validate_package(files: dict[str, bytes], inventory: dict[str, dict[str, str]]) -> list[str]:
    """Validate exactly the bytes destined for the installation ZIP."""
    failures: list[str] = []
    for name, data in files.items():
        path = PurePosixPath(name)
        allowed = (
            (len(path.parts) == 1 and path.suffix in {".py", ".json", ".yaml"})
            or (len(path.parts) == 2 and path.parts[0] == "translations" and path.suffix == ".json")
            or name in {"brand/icon.png", "brand/icon@2x.png", "LICENSE"}
        )
        if not allowed or any(part in {"", ".", ".."} for part in name.split("/")) or "\\" in name:
            failures.append("unexpected path in installation package")
            continue
        if path.suffix in MEDIA_SUFFIXES:
            entry = inventory.get(COMPONENT_PREFIX + name)
            if entry is None or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                failures.append(f"{name}: asset differs from documented provenance")
        else:
            failures.extend(content_issues(name, data))
    required = {"LICENSE", "manifest.json", "__init__.py"} | {
        path.removeprefix(COMPONENT_PREFIX) for path in inventory if path.startswith(COMPONENT_PREFIX)
    }
    if required - files.keys():
        failures.append("installation package is missing licensed/documented files")
    return failures


def check_files(root: Path = ROOT) -> list[str]:
    """Check tracked payloads, reviewed artwork and synthetic protocol fixtures."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True,
        )
        paths = {path.decode() for path in result.stdout.split(b"\0") if path}
        inventory = parse_inventory((root / PROVENANCE_PATH).read_bytes())
        legal = (root / "docs/legal.md").read_text(encoding="utf-8")
        license_text = (root / "LICENSE").read_text(encoding="utf-8")
        failures: list[str] = []
        if not {PROVENANCE_PATH, "docs/legal.md", "LICENSE"} <= paths:
            failures.append("legal documents must be tracked")
        if "MIT License" not in license_text or "permission notice shall be included" not in license_text:
            failures.append("project MIT license notice is missing")
        for phrase in ("unofficial community project", "not affiliated with", "All trademarks"):
            if phrase not in legal:
                failures.append("legal document lost its scope/trademark notice")
        media = {path for path in paths if PurePosixPath(path).suffix.lower() in MEDIA_SUFFIXES}
        if media != inventory.keys():
            failures.append("tracked media and provenance inventory differ")
        for path, entry in inventory.items():
            source = root / path
            if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest() != entry["sha256"]:
                failures.append(f"{path}: changed artwork needs provenance review")
            if f"`{path}`" not in legal:
                failures.append(f"{path}: missing human-readable legal inventory")
        package: dict[str, bytes] = {"LICENSE": (root / "LICENSE").read_bytes()}
        for path in sorted(paths):
            source = root / path
            if source.is_symlink():
                failures.append(f"{path}: tracked symlink requires review")
                continue
            if PurePosixPath(path).suffix.lower() in FORBIDDEN_SUFFIXES:
                failures.append(f"{path}: captured/binary/archive payload must not be tracked")
            if path.startswith(COMPONENT_PREFIX):
                package[path.removeprefix(COMPONENT_PREFIX)] = source.read_bytes()
            if path.startswith("tests/fixtures/"):
                if source.suffix != ".json":
                    failures.append(f"{path}: undocumented fixture format")
                    continue
                data = source.read_bytes()
                fixture = json.loads(data)
                if not isinstance(fixture, dict) or fixture.get("provenance") != FIXTURE_PROVENANCE:
                    failures.append(f"{path}: fixture must declare its synthetic provenance")
                failures.extend(content_issues(path, data))
        failures.extend(validate_package(package, inventory))
        return failures
    except (OSError, TypeError, ValueError, subprocess.CalledProcessError):
        return ["legal audit could not read tracked files or provenance documents"]


def main() -> int:
    failures = check_files()
    for failure in failures:
        print(f"ERROR: {failure}", file=sys.stderr)
    if not failures:
        print("asset/protocol provenance and installation-content checks passed")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
