"""Focused provenance and package-content regression tests."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts import check_legal_audit as check


def track(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "add", "."], check=True, capture_output=True)


@pytest.fixture
def legal_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/legal.md").write_text(
        "unofficial community project; not affiliated with; All trademarks\n"
        f"`{check.COMPONENT_PREFIX}brand/icon.png`\n"
    )
    (tmp_path / "LICENSE").write_text("MIT License\npermission notice shall be included\n")
    component = tmp_path / check.COMPONENT_PREFIX
    (component / "brand").mkdir(parents=True)
    (component / "brand/icon.png").write_bytes(b"synthetic artwork fixture")
    (component / "__init__.py").write_text("")
    (component / "manifest.json").write_text("{}")
    inventory = {"version": 1, "assets": {
        f"{check.COMPONENT_PREFIX}brand/icon.png": {
            "sha256": hashlib.sha256(b"synthetic artwork fixture").hexdigest(),
            "origin": "Synthetic test fixture", "rights": "MIT",
        },
    }}
    (tmp_path / check.PROVENANCE_PATH).write_text(json.dumps(inventory))
    fixture = tmp_path / "tests/fixtures/firmware_a/replay.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(json.dumps({"provenance": check.FIXTURE_PROVENANCE}))
    track(tmp_path)
    return tmp_path


def test_documented_repository_passes(legal_repo: Path) -> None:
    assert not check.check_files(legal_repo)


@pytest.mark.parametrize("mutation", ["changed", "new", "deleted", "origin", "license", "fixture", "capture", "symlink"])
def test_provenance_drift_fails(legal_repo: Path, mutation: str) -> None:
    icon = legal_repo / check.COMPONENT_PREFIX / "brand/icon.png"
    if mutation == "changed":
        icon.write_bytes(b"replacement")
    elif mutation == "new":
        (icon.parent / "logo.png").write_bytes(b"unreviewed artwork")
    elif mutation == "deleted":
        icon.unlink()
    elif mutation == "origin":
        path = legal_repo / check.PROVENANCE_PATH
        payload = json.loads(path.read_text())
        payload["assets"][f"{check.COMPONENT_PREFIX}brand/icon.png"]["origin"] = " "
        path.write_text(json.dumps(payload))
    elif mutation == "license":
        (legal_repo / "LICENSE").write_text("missing notice")
    elif mutation == "fixture":
        (legal_repo / "tests/fixtures/firmware_a/replay.json").write_text("{}")
    elif mutation == "capture":
        (legal_repo / "traffic.har").write_text("capture fixture")
    else:
        icon.unlink()
        icon.symlink_to(legal_repo / "LICENSE")
    track(legal_repo)
    assert check.check_files(legal_repo)


@pytest.mark.parametrize("name", ["../other.py", "brand/vendor.png", "token.txt", "traffic.har", "ste-dhe-app.js", "__pycache__/cached.pyc"])
def test_package_rejects_unexpected_files(name: str) -> None:
    assert check.validate_package({"LICENSE": b"MIT", "manifest.json": b"{}", "__init__.py": b"", name: b"fixture"}, {})


def test_package_reports_categories_without_secret_values() -> None:
    secret = "ghp_" + "X" * 40
    findings = check.validate_package({"manifest.json": secret.encode()}, {})
    assert any("github token" in item for item in findings)
    assert all(secret not in item for item in findings)


@pytest.mark.parametrize("payload", [
    b'{"version": 1, "assets": {}, "assets": {}}',
    b'{"version": 1, "assets": []}',
    b'{"version": 2, "assets": {}}',
])
def test_inventory_rejects_ambiguous_or_invalid_data(payload: bytes) -> None:
    with pytest.raises((TypeError, ValueError)):
        check.parse_inventory(payload)


def test_repository_assets_and_fixtures_have_reviewed_inventory() -> None:
    assert not check.check_files()
