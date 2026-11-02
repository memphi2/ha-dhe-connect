"""Offline regression tests for the opt-in GitHub audit."""

import io
import json
import zipfile
from unittest.mock import Mock

import pytest

from scripts import audit_github_public_surfaces as audit
from scripts.release_check import CommandResult


def zip_bytes(name: str, data: bytes) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(name, data)
    return output.getvalue()


def runner_for(payloads: dict[str, object], seen: list[str]):
    def runner(args):
        assert args[:2] == ["gh", "api"]
        assert args[3:] == ["--paginate"]
        endpoint = args[2]
        seen.append(endpoint)
        payload = payloads.get(endpoint, [])
        output = payload if isinstance(payload, str) else json.dumps(payload)
        return CommandResult(tuple(args), 0, output, "")
    return runner


def test_audit_reads_later_pages_and_review_bodies_without_leaking_matches() -> None:
    private = "10." + "12.34.56"
    seen: list[str] = []
    runner = runner_for({
        "repos/example/repo/pulls?state=all&per_page=100": '[{"number": 1}]\n[{"number": 2}]',
        "repos/example/repo/pulls/2/reviews?per_page=100": [{"body": f"host {private}"}],
    }, seen)
    result = audit.audit_public_surfaces("example/repo", runner)
    assert not result.ok
    assert "pulls/2/reviews" in result.message
    assert private not in result.message
    assert any("pulls/1/reviews" in endpoint for endpoint in seen)


def test_release_asset_api_is_paginated_and_download_uses_numeric_id() -> None:
    secret = "ghp_" + "A" * 40
    data = zip_bytes("manifest.json", secret.encode())
    seen: list[str] = []
    runner = runner_for({
        "repos/example/repo/releases?per_page=100": [{"id": 12, "assets": []}],
        "repos/example/repo/releases/12/assets?per_page=100": [
            {"id": 42, "name": "install.ZIP", "size": len(data), "url": "https://example.invalid/untrusted"},
        ],
    }, seen)
    download = Mock(return_value=data)
    result = audit.audit_public_surfaces("example/repo", runner, download)
    assert not result.ok
    assert "release 12 asset 42" in result.message
    assert "github token" in result.message
    assert secret not in result.message
    download.assert_called_once_with("example/repo", 42)


@pytest.mark.parametrize("data", [b"not json", b"{\"private\": \"marker\"}", b"[null]", b""])
def test_invalid_api_collections_fail_closed(data: bytes) -> None:
    result = audit.audit_public_surfaces(
        "example/repo", runner_for({
            "repos/example/repo/pulls?state=all&per_page=100": data.decode(),
        }, []),
    )
    assert not result.ok
    assert "incomplete" in result.message
    assert "marker" not in result.message


def test_api_error_is_not_echoed() -> None:
    private = "do not echo credentials"
    result = audit.audit_public_surfaces(
        "example/repo", lambda args: CommandResult(tuple(args), 1, "", private),
    )
    assert not result.ok
    assert private not in result.message


def test_empty_repository_passes_without_downloading() -> None:
    download = Mock()
    result = audit.audit_public_surfaces("example/repo", runner_for({}, []), download)
    assert result.ok
    download.assert_not_called()


@pytest.mark.parametrize("repo", ["../other", "https://example.invalid/repo", "-R evil", "owner/repo/path"])
def test_invalid_repositories_do_not_call_gh(repo: str) -> None:
    runner = Mock()
    assert not audit.audit_public_surfaces(repo, runner).ok
    runner.assert_not_called()


@pytest.mark.parametrize("name", ["../token", "/root/token", "a/../token", "C:\\token", "a//token"])
def test_zip_rejects_unsafe_paths(name: str) -> None:
    assert "unsafe or duplicate ZIP member" in audit.scan_zip(zip_bytes(name, b"fixture"))


def test_zip_rejects_symlinks_corruption_and_size_limits(monkeypatch) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        archive.writestr(info, "target")
    assert "unsafe or duplicate ZIP member" in audit.scan_zip(output.getvalue())
    assert audit.scan_zip(b"invalid") == {"unreadable ZIP asset"}
    monkeypatch.setattr(audit, "MAX_MEMBER_BYTES", 4)
    assert "ZIP member exceeds audit size limit" in audit.scan_zip(zip_bytes("file", b"12345"))
    monkeypatch.setattr(audit, "MAX_ZIP_MEMBERS", 0)
    assert "ZIP exceeds audit expansion limit" in audit.scan_zip(zip_bytes("file", b"a"))


@pytest.mark.parametrize("size", [-1, audit.MAX_ASSET_BYTES + 1, None])
def test_asset_size_guard_prevents_download(size: int | None) -> None:
    download = Mock()
    runner = runner_for({
        "repos/example/repo/releases?per_page=100": [{"id": 1}],
        "repos/example/repo/releases/1/assets?per_page=100": [{"id": 2, "size": size, "name": "test.zip"}],
    }, [])
    assert not audit.audit_public_surfaces("example/repo", runner, download).ok
    download.assert_not_called()


def test_plain_attachment_is_scanned_and_download_errors_fail_closed() -> None:
    data = ('"access_token": "' + "A" * 40 + '"').encode()
    runner = runner_for({
        "repos/example/repo/releases?per_page=100": [{"id": 1}],
        "repos/example/repo/releases/1/assets?per_page=100": [{"id": 2, "size": len(data), "name": "log.txt"}],
    }, [])
    result = audit.audit_public_surfaces("example/repo", runner, Mock(return_value=data))
    assert not result.ok
    assert "JSON access token" in result.message
    result = audit.audit_public_surfaces("example/repo", runner, Mock(side_effect=OSError("private")))
    assert not result.ok
    assert "private" not in result.message
