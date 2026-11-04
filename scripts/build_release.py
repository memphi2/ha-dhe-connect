"""Build or verify reproducible release assets from the committed Git tree."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

try:
    from scripts.check_legal_audit import (
        PROVENANCE_PATH,
        parse_inventory,
        validate_package,
    )
except ModuleNotFoundError:
    from check_legal_audit import PROVENANCE_PATH, parse_inventory, validate_package

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "stiebel_dhe_connect"
REPOSITORY = "memphi2/ha-dhe-connect"
ZIP_NAME = "ha-dhe-connect.zip"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
ASSET_NAMES = {ZIP_NAME, "build-metadata.json", "sbom.spdx.json", "SHA256SUMS"}


def _git(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=False
    )
    if result.returncode:
        raise ValueError("cannot read release source from Git")
    return result.stdout


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_files(root: Path, commit: str) -> dict[str, bytes]:
    """Read only committed regular component files and the project license."""
    prefix = f"custom_components/{DOMAIN}/"
    entries = _git(root, "ls-tree", "-rz", commit, "--", prefix, "LICENSE")
    files: dict[str, bytes] = {}
    for entry in entries.split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8")
        name = path.removeprefix(prefix)
        parts = PurePosixPath(name).parts
        if (
            kind != "blob"
            or mode not in {"100644", "100755"}
            or any(part.startswith(".") or part == "__pycache__" for part in parts)
            or "\\" in name
            or PurePosixPath(name).suffix in {".pyc", ".pyo"}
        ):
            raise ValueError("release source contains a non-regular or generated file")
        if name in files:
            raise ValueError("release source contains a duplicate package path")
        files[name] = _git(root, "cat-file", "blob", oid)
    if not {"manifest.json", "__init__.py", "LICENSE"} <= files.keys():
        raise ValueError("release source is missing component files or LICENSE")
    return files


def build_assets(root: Path = ROOT) -> dict[str, bytes]:
    """Return deterministic assets for HEAD; never package untracked files."""
    if _git(root, "status", "--porcelain", "--untracked-files=no").strip():
        raise ValueError("commit tracked changes before building release assets")
    commit = _git(root, "rev-parse", "HEAD").decode().strip()
    files = source_files(root, commit)
    inventory = parse_inventory(_git(root, "show", f"{commit}:{PROVENANCE_PATH}"))
    if failures := validate_package(files, inventory):
        raise ValueError("release package failed provenance/content checks: " + "; ".join(failures))
    manifest = json.loads(files["manifest.json"])
    version = manifest.get("version", "")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("release manifest must contain a stable version")
    if manifest.get("domain") != DOMAIN or manifest.get("requirements") != []:
        raise ValueError("review the release inventory after changing domain or requirements")
    buffer = io.BytesIO()
    # Stored entries avoid zlib-version drift; Git blob bytes are not newline-converted.
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=ZIP_TIMESTAMP)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    package = buffer.getvalue()
    digest = _sha256(package)
    created = datetime.fromtimestamp(
        int(_git(root, "show", "-s", "--format=%ct", commit)), UTC
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    assets = {
        ZIP_NAME: package,
        "build-metadata.json": _json_bytes({
            "repository": REPOSITORY,
            "git_commit": commit,
            "source_date": created,
            "release_tag": f"v{version}",
            "integration_version": version,
            "zip_sha256": digest,
            "files": {name: _sha256(data) for name, data in sorted(files.items())},
        }),
        "sbom.spdx.json": _json_bytes({
            "spdxVersion": "SPDX-2.3",
            "dataLicense": "CC0-1.0",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": f"ha-dhe-connect-{version}",
            "documentNamespace": f"https://github.com/{REPOSITORY}/sbom/{commit}-{digest}",
            "creationInfo": {
                "created": created,
                "creators": ["Tool: ha-dhe-connect-build-release"],
            },
            "comment": (
                "Integration archive inventory only. No bundled third-party dependencies; "
                "Home Assistant and its environment are not included."
            ),
            "packages": [{
                "SPDXID": "SPDXRef-Integration",
                "name": "ha-dhe-connect",
                "versionInfo": version,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseDeclared": "MIT",
                "licenseConcluded": "NOASSERTION",
                "copyrightText": "NOASSERTION",
                "checksums": [{"algorithm": "SHA256", "checksumValue": digest}],
            }],
            "relationships": [{
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": "SPDXRef-Integration",
            }],
        }),
    }
    assets["SHA256SUMS"] = "".join(
        f"{_sha256(data)}  {name}\n" for name, data in sorted(assets.items())
    ).encode()
    return assets


def verify_assets(directory: Path, assets: dict[str, bytes]) -> None:
    """Compare downloaded assets with a rebuild, not just their own checksums."""
    for name, expected in assets.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.read_bytes() != expected:
            raise ValueError(f"release asset differs from committed source: {name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--output-dir", type=Path, default=ROOT / ".release")
    group.add_argument("--verify", type=Path, help="Compare downloaded assets to HEAD")
    args = parser.parse_args(argv)
    try:
        assets = build_assets()
        if args.verify is not None:
            verify_assets(args.verify, assets)
        else:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            for name, data in assets.items():
                target = args.output_dir / name
                if target.is_symlink():
                    raise ValueError("release output must not contain symlinks")
                target.write_bytes(data)
            verify_assets(args.output_dir, assets)
    except (OSError, TypeError, ValueError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    print("release assets match committed source (ZIP, metadata, SPDX inventory, SHA256SUMS)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
