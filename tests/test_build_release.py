"""Release assets must be reproducible, source-bound and credential-free."""

import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts import build_release


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def release_repo(tmp_path: Path) -> Path:
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "Release test")
    component = tmp_path / "custom_components" / build_release.DOMAIN
    component.mkdir(parents=True)
    (component / "manifest.json").write_text(json.dumps({
        "domain": build_release.DOMAIN, "version": "2.0.10", "requirements": [],
    }))
    (component / "__init__.py").write_text('"""Test integration."""\n')
    (tmp_path / "LICENSE").write_text("Test license\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/asset_provenance.json").write_text('{"version": 1, "assets": {}}')
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "Fixture")
    return tmp_path


def test_assets_reproduce_source_and_checksums(release_repo: Path) -> None:
    assets = build_release.build_assets(release_repo)
    assert assets == build_release.build_assets(release_repo)
    assert set(assets) == build_release.ASSET_NAMES
    metadata = json.loads(assets["build-metadata.json"])
    with zipfile.ZipFile(io.BytesIO(assets[build_release.ZIP_NAME])) as archive:
        assert archive.namelist() == sorted(metadata["files"])
        for info in archive.infolist():
            assert info.date_time == build_release.ZIP_TIMESTAMP
            assert info.external_attr >> 16 == 0o100644
            assert hashlib.sha256(archive.read(info)).hexdigest() == metadata["files"][info.filename]
    for line in assets["SHA256SUMS"].decode().splitlines():
        digest, name = line.split("  ")
        assert digest == hashlib.sha256(assets[name]).hexdigest()
    sbom = json.loads(assets["sbom.spdx.json"])
    assert set(sbom) == {
        "spdxVersion", "dataLicense", "SPDXID", "name", "documentNamespace",
        "creationInfo", "comment", "packages", "relationships",
    }
    assert sbom["packages"][0]["checksums"][0]["checksumValue"] == metadata["zip_sha256"]
    assert sbom["creationInfo"]["created"] == metadata["source_date"]


def test_untracked_files_cannot_enter_archive(release_repo: Path) -> None:
    before = build_release.build_assets(release_repo)
    component = release_repo / "custom_components" / build_release.DOMAIN
    (component / "local-token.txt").write_text("private fixture")
    (component / "__pycache__").mkdir()
    (component / "__pycache__" / "cache.pyc").write_bytes(b"cache")
    assert build_release.build_assets(release_repo) == before


def test_dirty_source_is_rejected(release_repo: Path) -> None:
    (release_repo / "LICENSE").write_text("changed")
    with pytest.raises(ValueError, match="commit tracked changes"):
        build_release.build_assets(release_repo)


@pytest.mark.parametrize("name", ["__pycache__/cache.pyc", "link.py", ".token"])
def test_unsafe_tracked_sources_are_rejected(release_repo: Path, name: str) -> None:
    target = release_repo / "custom_components" / build_release.DOMAIN / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if name == "link.py":
        target.symlink_to(release_repo / "LICENSE")
    else:
        target.write_text("fixture")
    git(release_repo, "add", ".")
    git(release_repo, "commit", "-m", "Unsafe fixture")
    with pytest.raises(ValueError, match="non-regular or generated"):
        build_release.build_assets(release_repo)


@pytest.mark.parametrize("name", sorted(build_release.ASSET_NAMES))
def test_verification_detects_tampering(release_repo: Path, name: str) -> None:
    assets = build_release.build_assets(release_repo)
    destination = release_repo / "downloaded"
    destination.mkdir()
    for filename, data in assets.items():
        (destination / filename).write_bytes(data)
    build_release.verify_assets(destination, assets)
    (destination / name).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="differs from committed source"):
        build_release.verify_assets(destination, assets)
