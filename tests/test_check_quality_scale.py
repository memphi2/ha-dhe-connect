"""Quality inventory validation must fail on structural and evidence drift."""

from pathlib import Path

import pytest
import yaml

from scripts import check_quality_scale as check


@pytest.fixture
def inventory() -> dict:
    return yaml.safe_load((check.ROOT / check.QUALITY_PATH).read_text())


def validate(data: dict, docs: str | None = None) -> list[str]:
    return check.validate_quality_scale(
        yaml.safe_dump(data), docs if docs is not None else (check.ROOT / check.DOC_PATH).read_text(),
    )


def test_complete_local_inventory_passes() -> None:
    assert len(check.ALL_RULES) == 54
    assert check.check_files() == []


@pytest.mark.parametrize("mutation", ["missing", "extra", "status", "comment", "downgrade", "evidence", "blank", "group"])
def test_drift_is_rejected(inventory: dict, mutation: str) -> None:
    if mutation == "missing":
        del inventory["rules"]["diagnostics"]
    elif mutation == "extra":
        inventory["rules"]["unknown-rule"] = "done"
    elif mutation == "status":
        inventory["rules"]["diagnostics"] = {"status": []}
    elif mutation == "comment":
        inventory["rules"]["docs-triggers"] = "exempt"
    elif mutation == "downgrade":
        inventory["rules"]["strict-typing"] = {"status": "exempt", "comment": "Reason"}
    elif mutation == "evidence":
        del inventory["evidence"]["platinum"]["strict-typing"]
    elif mutation == "blank":
        inventory["evidence"]["gold"]["devices"]["tests"] = " "
    else:
        inventory["evidence"]["other"] = {}
    assert validate(inventory)


def test_todo_requires_consistent_docs_and_reason(inventory: dict) -> None:
    inventory["rules"]["diagnostics"] = {"status": "todo", "comment": "Needs further evidence"}
    docs = (check.ROOT / check.DOC_PATH).read_text()
    assert validate(inventory, docs)
    assert not validate(inventory, docs.replace("Open rules: none", "Open rules: `diagnostics`"))
    del inventory["rules"]["diagnostics"]["comment"]
    assert validate(inventory, docs.replace("Open rules: none", "Open rules: `diagnostics`"))


@pytest.mark.parametrize("text", ["rules: {}\nrules: {}", "rules: {devices: done, devices: todo}", "[", "[]", "rules: []\nevidence: {}"])
def test_malformed_or_duplicate_yaml_is_rejected(text: str) -> None:
    assert check.validate_quality_scale(text, "")


def test_missing_files_and_missing_unofficial_statement_fail(tmp_path: Path, inventory: dict) -> None:
    assert check.check_files(tmp_path)
    assert validate(inventory, "Open rules: none")
