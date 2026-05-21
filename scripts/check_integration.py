"""Lightweight repository checks for the DHE Connect integration."""

from __future__ import annotations

import json
import re
import sys
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "stiebel_dhe_connect"
TRANSLATIONS = INTEGRATION / "translations"
CLIENT_MODULE_MAX_BYTES = 50 * 1024
SILVER_RULES = {
    # Bronze
    "action-setup",
    "appropriate-polling",
    "brands",
    "common-modules",
    "config-flow-test-coverage",
    "config-flow",
    "dependency-transparency",
    "docs-actions",
    "docs-high-level-description",
    "docs-installation-instructions",
    "docs-removal-instructions",
    "entity-unique-id",
    "has-entity-name",
    "runtime-data",
    "test-before-configure",
    "test-before-setup",
    "unique-config-entry",
    # Silver
    "action-exceptions",
    "config-entry-unloading",
    "docs-configuration-parameters",
    "docs-installation-parameters",
    "entity-unavailable",
    "integration-owner",
    "log-when-unavailable",
    "parallel-updates",
    "reauthentication-flow",
    "test-coverage",
}
GOLD_CORE_RULES = {
    "reconfiguration-flow",
    "repair-issues",
}
PINNED_VALIDATION_ACTIONS = {
    "actions/checkout",
    "actions/setup-python",
    "hacs/action",
    "home-assistant/actions/hassfest",
}
NODE24_VALIDATION_ACTION_MAJORS = {
    "actions/checkout": 6,
    "actions/setup-python": 6,
}
NODE24_VALIDATION_ACTION_PINS = {
    # v6 tags resolved on 2026-05-20. Keep these in sync with
    # .github/workflows/validate.yml when refreshing action pins.
    "actions/checkout": {"de0fac2e4500dabe0009e67214ff5f5447ce83dd"},
    "actions/setup-python": {"a309ff8b426b58ec0e2a45f0f869d46889d02405"},
}
_ACTION_REF_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*([^@\s]+)@([^\s#]+)", re.MULTILINE)
_MAJOR_VERSION_REF_RE = re.compile(r"^v(?P<major>\d+)(?:\.|$)")


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file, object_pairs_hook=_reject_duplicate_json_keys(path))


def _reject_duplicate_json_keys(path: Path):
    """Return an object hook that rejects duplicate keys in JSON objects."""
    def _object_pairs_hook(pairs):
        data = {}
        for key, value in pairs:
            if key in data:
                _fail(f"duplicate JSON key {key!r} in {path.relative_to(ROOT)}")
            data[key] = value
        return data

    return _object_pairs_hook


def _fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def _entity_translation_keys(data: dict) -> dict[str, set[str]]:
    entity = data.get("entity")
    if not isinstance(entity, dict):
        _fail("translation file is missing the entity section")
    return {
        platform: set(platform_data)
        for platform, platform_data in entity.items()
        if isinstance(platform_data, dict)
    }


def check_manifest() -> str:
    manifest = _load_json(INTEGRATION / "manifest.json")
    required = {
        "domain": "stiebel_dhe_connect",
        "name": "DHE Connect",
        "config_flow": True,
        "iot_class": "local_push",
        "integration_type": "device",
    }
    for key, expected in required.items():
        if manifest.get(key) != expected:
            _fail(f"manifest {key!r} is {manifest.get(key)!r}, expected {expected!r}")
    if not isinstance(manifest.get("requirements"), list):
        _fail("manifest requirements must be a list")
    version = str(manifest.get("version", "")).strip()
    if not version:
        _fail("manifest version is missing")
    return version


def check_hacs() -> None:
    hacs = _load_json(ROOT / "hacs.json")
    if hacs.get("name") != "DHE Connect":
        _fail("hacs.json name does not match the integration name")
    if hacs.get("render_readme") is not True:
        _fail("hacs.json render_readme must be true")


def check_repository_files(version: str) -> None:
    for relative in (
        "README.md",
        "CHANGELOG.md",
        "LICENSE",
        "hacs.json",
        "custom_components/stiebel_dhe_connect/services.yaml",
        "custom_components/stiebel_dhe_connect/quality_scale.yaml",
        "custom_components/stiebel_dhe_connect/brand/icon.png",
        "custom_components/stiebel_dhe_connect/brand/logo.png",
        "docs/troubleshooting.md",
        "docs/validation.md",
        "docs/examples.md",
        "docs/use-cases.md",
        "docs/known_limitations.md",
        "docs/legal.md",
    ):
        if not (ROOT / relative).exists():
            _fail(f"required file missing: {relative}")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"Current version: `{version}`" not in readme:
        _fail("README current version does not match manifest version")
    if f"## v{version}" not in changelog:
        _fail("CHANGELOG is missing a section for the manifest version")
    if "[docs/troubleshooting.md](docs/troubleshooting.md)" not in readme:
        _fail("README troubleshooting reference points to docs/troubleshooting.md")
    if "[docs/validation.md](docs/validation.md)" not in readme:
        _fail("README validation reference points to docs/validation.md")
    if "[docs/examples.md](docs/examples.md)" not in readme:
        _fail("README examples reference points to docs/examples.md")
    if "[docs/use-cases.md](docs/use-cases.md)" not in readme:
        _fail("README use-cases reference points to docs/use-cases.md")
    if "[docs/known_limitations.md](docs/known_limitations.md)" not in readme:
        _fail("README known-limitations reference points to docs/known_limitations.md")
    if "[docs/legal.md](docs/legal.md)" not in readme:
        _fail("README legal reference points to docs/legal.md")
    if "### Removal" not in readme:
        _fail("README is missing removal instructions")
    if (ROOT / "info.md").exists():
        _fail("legacy info.md release notes must not be restored; use CHANGELOG.md")


def check_gold_evidence_docs() -> None:
    """Ensure Gold evidence docs keep required structure."""
    firmware_matrix = (ROOT / "docs" / "firmware_matrix.md").read_text(encoding="utf-8")
    validation = (ROOT / "docs" / "validation.md").read_text(encoding="utf-8")

    firmware_required_sections = (
        "## Required Evidence Fields",
        "## Evidence Entry Template",
        "## Current Evidence Snapshot",
    )
    for section in firmware_required_sections:
        if section not in firmware_matrix:
            _fail(f"docs/firmware_matrix.md is missing section: {section}")

    validation_required_sections = (
        "## Gold Evidence Log Template",
        "## Icon Translation Status",
    )
    for section in validation_required_sections:
        if section not in validation:
            _fail(f"docs/validation.md is missing section: {section}")


def _quality_scale_done_rules(text: str) -> set[str]:
    """Return rule IDs whose quality-scale status is done."""
    done: set[str] = set()
    current_rule: str | None = None
    for line in text.splitlines():
        rule_match = re.match(r"^  ([a-z0-9-]+):(?:\s*(done|todo))?\s*$", line)
        if rule_match:
            current_rule = rule_match.group(1)
            if rule_match.group(2) == "done":
                done.add(current_rule)
            continue
        status_match = re.match(r"^    status:\s*(done|todo|exempt)\s*$", line)
        if status_match and current_rule and status_match.group(1) == "done":
            done.add(current_rule)
    return done


def check_quality_scale() -> None:
    """Ensure tracked Home Assistant Silver and Gold-core rules stay done."""
    path = INTEGRATION / "quality_scale.yaml"
    done = _quality_scale_done_rules(path.read_text(encoding="utf-8"))
    missing = sorted((SILVER_RULES | GOLD_CORE_RULES) - done)
    if missing:
        _fail(f"quality_scale.yaml is missing required done rules: {missing}")


def check_github_actions() -> None:
    workflow = ROOT / ".github" / "workflows" / "validate.yml"
    if not workflow.exists():
        _fail("validation workflow is missing")
    text = workflow.read_text(encoding="utf-8")
    action_refs = _workflow_action_refs(text)
    refs_by_action: dict[str, list[str]] = {
        action: action_refs.get(action, []) for action in PINNED_VALIDATION_ACTIONS
    }

    missing = sorted(
        action for action, refs in refs_by_action.items() if not refs
    )
    if missing:
        _fail(f"validation workflow is missing actions: {', '.join(missing)}")
    for action, refs in sorted(refs_by_action.items()):
        for ref in refs:
            if not re.fullmatch(r"[0-9a-f]{40}", ref):
                _fail(f"{action} must be pinned to a 40-character commit SHA")
    for action, minimum_major in sorted(NODE24_VALIDATION_ACTION_MAJORS.items()):
        refs = action_refs.get(action, [])
        if not refs:
            _fail(f"validation workflow is missing {action}")
        for ref in refs:
            if (
                ref not in NODE24_VALIDATION_ACTION_PINS.get(action, set())
                and not _action_ref_has_minimum_major(ref, minimum_major)
            ):
                _fail(
                    f"{action}@{ref} must be v{minimum_major} or newer "
                    "to avoid GitHub Actions Node.js 20 runtime warnings"
                )


def _workflow_action_refs(text: str) -> dict[str, list[str]]:
    """Return workflow action refs grouped by action name."""
    refs: dict[str, list[str]] = {}
    for action, ref in _ACTION_REF_RE.findall(text):
        refs.setdefault(action, []).append(ref)
    return refs


def _action_ref_has_minimum_major(ref: str, minimum_major: int) -> bool:
    """Return whether an action ref is a vN tag at or above the required major."""
    match = _MAJOR_VERSION_REF_RE.match(ref)
    return match is not None and int(match.group("major")) >= minimum_major


def check_client_module_size() -> None:
    client = INTEGRATION / "client.py"
    size = client.stat().st_size
    if size > CLIENT_MODULE_MAX_BYTES:
        _fail(
            f"client.py is {size} bytes, expected <= {CLIENT_MODULE_MAX_BYTES} bytes"
        )


def check_translations() -> None:
    en = _load_json(TRANSLATIONS / "en.json")
    de = _load_json(TRANSLATIONS / "de.json")
    en_keys = _entity_translation_keys(en)
    de_keys = _entity_translation_keys(de)
    if set(en_keys) != set(de_keys):
        _fail("translation platform sections differ between en.json and de.json")
    for platform in sorted(en_keys):
        if en_keys[platform] != de_keys[platform]:
            missing_de = sorted(en_keys[platform] - de_keys[platform])
            missing_en = sorted(de_keys[platform] - en_keys[platform])
            _fail(
                f"translation keys differ for {platform}: "
                f"missing in de={missing_de}, missing in en={missing_en}"
            )


def check_type_gate_coverage() -> None:
    """Ensure every integration module is covered by the scoped type gate."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    configured_files = pyproject.get("tool", {}).get("mypy", {}).get("files", [])
    if not isinstance(configured_files, list) or not all(
        isinstance(item, str) for item in configured_files
    ):
        _fail("tool.mypy.files must be a list of repository-relative file paths")
    mypy_files = set(configured_files)
    integration_modules = {
        str(path.relative_to(ROOT))
        for path in sorted(INTEGRATION.glob("*.py"))
        if path.is_file()
    }
    missing = sorted(integration_modules - mypy_files)
    if missing:
        _fail(f"mypy type gate is missing integration modules: {missing}")
    prefix = str(INTEGRATION.relative_to(ROOT)).replace("\\", "/") + "/"
    stale = sorted(
        file
        for file in mypy_files
        if file.startswith(prefix) and file.endswith(".py") and file not in integration_modules
    )
    if stale:
        _fail(f"mypy type gate references missing integration modules: {stale}")


def check_compile() -> None:
    for path in sorted(INTEGRATION.rglob("*.py")):
        try:
            source = path.read_text(encoding="utf-8")
            compile(source, str(path.relative_to(ROOT)), "exec")
        except SyntaxError as err:
            _fail(f"Python syntax check failed for {path.relative_to(ROOT)}: {err}")


def check_unit_tests() -> None:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=1).run(suite)
    if not result.wasSuccessful():
        _fail("unit tests failed")


def main() -> None:
    version = check_manifest()
    check_hacs()
    check_repository_files(version)
    check_gold_evidence_docs()
    check_quality_scale()
    check_github_actions()
    check_client_module_size()
    check_translations()
    check_type_gate_coverage()
    check_compile()
    check_unit_tests()
    print("integration checks ok")


if __name__ == "__main__":
    main()
