"""Exercise publication transactions without contacting GitHub or creating tags."""

import copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from scripts import publish_release as publish

TAG = "v2.0.10"
NOTES = "### Maintenance\n\n- Synthetic release verification."
CHANGELOG = f"# Changelog\n\n## Unreleased\n\n- No changes yet.\n\n## {TAG} - 2026-01-01\n\n{NOTES}\n"


@pytest.fixture
def github(tmp_path, monkeypatch):
    """Small stateful CLI/API fake with separately downloaded asset bytes."""
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG)
    monkeypatch.setattr(publish, "ROOT", tmp_path)
    assets = {name: name.encode() for name in publish.build.ASSET_NAMES}
    monkeypatch.setattr(publish.build, "build_assets", lambda _root: assets)
    monkeypatch.setattr(publish.checks, "load_manifest_version", lambda _root: "2.0.10")
    preflight = Mock(return_value=0)
    monkeypatch.setattr(publish.checks, "main", preflight)
    tag_check = Mock(return_value=SimpleNamespace(ok=True))
    monkeypatch.setattr(publish.checks, "check_github_tag_matches_head", tag_check)
    state = SimpleNamespace(release=None, files={}, commands=[], failure=None,
                            corrupt=False, assets=assets, preflight=preflight, tag_check=tag_check)

    def create(*, draft=True):
        state.release = {"id": 11, "name": TAG, "tag_name": TAG, "body": NOTES,
                         "draft": draft, "prerelease": False,
                         "published_at": None if draft else "2026-01-01T00:00:00Z"}

    def upload(name, data=None):
        state.files[name] = data if data is not None else assets[name]

    def items(endpoint, _runner):
        if endpoint.endswith("/releases?per_page=100"):
            return [copy.deepcopy(state.release)] if state.release is not None else []
        assert endpoint.endswith("/releases/11/assets?per_page=100")
        return [{"id": index, "name": name, "state": "uploaded"}
                for index, name in enumerate(state.files, 1)]

    def download(repo, asset_id):
        assert repo == publish.REPOSITORY
        return b"changed" if state.corrupt else list(state.files.values())[asset_id - 1]

    def run(args):
        assert args[:2] == ["gh", "release"]
        assert args[-2:] == ["--repo", publish.REPOSITORY]
        state.commands.append(args)
        command = args[2]
        if command == state.failure:
            return publish.checks.CommandResult(tuple(args), 1, "", "private server response")
        if command == "create":
            assert "--draft" in args and "--verify-tag" in args
            create()
            state.release["body"] = Path(args[args.index("--notes-file") + 1]).read_text()
        elif command == "upload":
            assert "--clobber" not in args
            for filename in args[4:-2]:
                path = Path(filename)
                assert path.name not in state.files
                upload(path.name, path.read_bytes())
        elif command == "edit":
            assert args[4] == "--draft=false"
            assert state.files == assets
            state.release.update(draft=False, published_at="2026-01-01T00:00:00Z")
        else:
            pytest.fail(f"unexpected write command {command}")
        return publish.checks.CommandResult(tuple(args), 0, "", "")

    state.create = create
    state.upload = upload
    monkeypatch.setattr(publish.audit, "_items", items)
    monkeypatch.setattr(publish.audit, "download_asset", download)
    monkeypatch.setattr(publish.checks, "run_command", run)
    return state


def test_new_release_is_verified_before_publication(github):
    assert publish.main(["--tag", TAG]) == 0
    assert [command[2] for command in github.commands] == ["create", "upload", "edit"]
    assert github.files == github.assets
    assert github.release["draft"] is False
    github.preflight.assert_called_once_with([
        "--expect-tag", "present", "--require-current-tag", "--expect-github-release", "skip",
    ])
    assert github.tag_check.call_count == 3


def test_existing_matching_release_is_read_only(github):
    github.create(draft=False)
    for name in github.assets:
        github.upload(name)
    publish.publish(TAG)
    assert not github.commands


def test_retry_resumes_only_missing_draft_assets(github):
    github.create()
    github.upload("SHA256SUMS")
    publish.publish(TAG)
    assert [command[2] for command in github.commands] == ["upload", "edit"]
    assert not any(Path(value).name == "SHA256SUMS" for value in github.commands[0][4:-2])


@pytest.mark.parametrize("failure", ["create", "upload", "edit"])
def test_cli_failure_never_claims_success_or_exposes_response(github, capsys, failure):
    github.failure = failure
    assert publish.main(["--tag", TAG]) == 1
    assert github.release is None or github.release["draft"]
    output = capsys.readouterr()
    assert "private server response" not in output.out + output.err


@pytest.mark.parametrize("draft", [True, False])
def test_changed_assets_are_never_overwritten(github, draft):
    github.create(draft=draft)
    github.upload("SHA256SUMS", b"tampered")
    with pytest.raises(ValueError, match="differs from committed source"):
        publish.publish(TAG)
    assert not github.commands


def test_post_upload_corruption_keeps_release_draft(github):
    github.corrupt = True
    with pytest.raises(ValueError, match="differs from committed source"):
        publish.publish(TAG)
    assert github.release["draft"]
    assert "edit" not in [command[2] for command in github.commands]


@pytest.mark.parametrize("field,value", [
    ("body", "wrong notes"), ("name", "wrong title"), ("prerelease", True), ("draft", None),
])
def test_different_release_metadata_requires_manual_attention(github, field, value):
    github.create()
    github.release[field] = value
    with pytest.raises(ValueError, match="metadata differs"):
        publish.publish(TAG)
    assert not github.commands


def test_incomplete_published_release_is_not_modified(github):
    github.create(draft=False)
    with pytest.raises(ValueError, match="missing assets"):
        publish.publish(TAG)
    assert not github.commands


def test_unknown_asset_is_rejected(github):
    github.create()
    github.upload("unexpected.txt", b"extra")
    with pytest.raises(ValueError, match="unexpected"):
        publish.publish(TAG)
    assert not github.commands


@pytest.mark.parametrize("failure_at", [0, 1, 2])
def test_remote_tag_is_checked_before_and_after_publication(github, failure_at):
    github.tag_check.side_effect = [SimpleNamespace(ok=index != failure_at) for index in range(3)]
    with pytest.raises(ValueError, match="remote release tag"):
        publish.publish(TAG)
    if failure_at < 2:
        assert github.release is None or github.release["draft"]


def test_failed_stable_baseline_or_source_preflight_prevents_all_writes(github):
    github.preflight.return_value = 1
    with pytest.raises(ValueError, match="preflight failed"):
        publish.publish(TAG)
    assert not github.commands
    github.tag_check.assert_not_called()


def test_manifest_mismatch_prevents_all_writes(github, monkeypatch):
    monkeypatch.setattr(publish.checks, "load_manifest_version", lambda _root: "2.0.11")
    with pytest.raises(ValueError, match="manifest"):
        publish.publish(TAG)
    assert not github.commands


@pytest.mark.parametrize("changelog,tag", [
    (CHANGELOG, "v2.0.10-beta"), (CHANGELOG, "--draft"), (CHANGELOG, "v2.0.11"),
    (CHANGELOG.replace("2026-01-01", "Unreleased"), TAG),
    (CHANGELOG.replace("2026-01-01", "9999-01-01"), TAG),
    (CHANGELOG.replace("2026-01-01", "2026-02-30"), TAG),
    (CHANGELOG.replace(NOTES, ""), TAG),
    (CHANGELOG.replace(NOTES, "- No changes yet."), TAG),
])
def test_invalid_release_notes_are_rejected(changelog, tag):
    with pytest.raises(ValueError):
        publish.release_notes(changelog, tag)


def test_notes_exclude_other_versions():
    assert publish.release_notes(CHANGELOG + "\n## v2.0.9 - 2025-12-01\n\nOlder notes", TAG) == NOTES


def test_release_workflow_requires_tag_validation_and_scoped_write_access():
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.load((root / ".github/workflows/release.yml").read_text(), Loader=yaml.BaseLoader)
    validation = yaml.load((root / ".github/workflows/validate.yml").read_text(), Loader=yaml.BaseLoader)
    assert workflow["on"] == {"push": {"tags": ["v*"]}, "workflow_dispatch": ""}
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == {"group": "release-${{ github.ref }}", "cancel-in-progress": "false"}
    assert workflow["jobs"]["validation"] == {
        "if": "github.repository == 'memphi2/ha-dhe-connect' && startsWith(github.ref, 'refs/tags/v')",
        "uses": "./.github/workflows/validate.yml",
    }
    assert validation["on"]["workflow_call"] == ""
    assert validation["on"]["push"] == {"branches": ["main"]}
    assert validation["jobs"]["home-assistant-latest"]["if"] == (
        "(github.event_name == 'schedule' || github.event_name == 'workflow_dispatch') && github.workflow == 'Validate'"
    )
    job = workflow["jobs"]["publish"]
    assert job["needs"] == "validation"
    assert "if" not in job and "continue-on-error" not in job
    assert job["permissions"] == {"contents": "write"}
    steps = job["steps"]
    assert all("if" not in step and "continue-on-error" not in step for step in steps)
    assert steps[0]["with"] == {"ref": "${{ github.sha }}", "fetch-depth": "0", "persist-credentials": "false"}
    expected_actions = {step["uses"] for step in validation["jobs"]["repository"]["steps"] if "uses" in step}
    assert {step["uses"] for step in steps if "uses" in step} == expected_actions
    assert [step["run"] for step in steps if "run" in step] == [
        "python -m pip install -r requirements.txt", "python -m pip check",
        'python scripts/publish_release.py --tag "$RELEASE_TAG"',
    ]
    assert steps[-1]["env"] == {"GH_TOKEN": "${{ github.token }}", "RELEASE_TAG": "${{ github.ref_name }}"}
