"""Lightweight repository checks for the DHE Connect integration."""

from __future__ import annotations

import json
import re
import shlex
import sys
import tomllib
import unittest
from pathlib import Path

import yaml
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

try:
    from scripts.ha_baseline import read_baseline
except ModuleNotFoundError:
    from ha_baseline import read_baseline

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "stiebel_dhe_connect"
INTEGRATION_NAME = "Stiebel Eltron DHE Connect"
TRANSLATIONS = INTEGRATION / "translations"
FIXTURE_ROOT = ROOT / "tests" / "fixtures"
REPLAY_FIXTURE_NAME = "dhe_protocol_replay_sanitized.json"
CLIENT_MODULE_MAX_BYTES = 50 * 1024
MIN_HOMEASSISTANT_VERSION = "2026.10.4"
NEXT_HOMEASSISTANT_SERIES = "2026.11"
VALIDATION_PYTHON_VERSION = "3.14"
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
REQUIRED_VALIDATION_ACTIONS = {
    "actions/checkout",
    "actions/setup-python",
    "hacs/action",
    "home-assistant/actions/hassfest",
}
NODE24_VALIDATION_ACTION_MAJORS = {
    "actions/checkout": 7,
    "actions/setup-python": 7,
}
VALIDATION_DEPENDENCY_MINIMUMS = {
    "pytest-cov": ">=7.1,<8",
}
VALIDATION_TOOL_BOUNDS = {
    "mypy": ("2.4", "3"),
    "ruff": ("0.17", "0.18"),
}
_ACTION_REF_RE = re.compile(
    r"^\s*(?:-\s*)?uses:\s*([^@\s]+)@([^\s#]+)(?:\s+#\s*([^\s]+))?",
    re.MULTILINE,
)
_USES_LINE_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*\S+", re.MULTILINE)
_MAJOR_VERSION_REF_RE = re.compile(r"^v(?P<major>\d+)(?:\.|$)")
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
README_REQUIRED_DOC_LINKS = {
    "docs/installation.md",
    "docs/troubleshooting.md",
    "docs/examples.md",
    "docs/use-cases.md",
    "docs/known_limitations.md",
    "docs/legal.md",
}
STABLE_CHANGELOG_DISALLOWED_TERMS = (
    "beta",
    "pre-release",
    "prerelease",
    "release candidate",
    "rc ",
)


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


def _markdown_link_targets(text: str) -> set[str]:
    """Return Markdown link targets from text."""
    return {target.strip() for target in _MARKDOWN_LINK_RE.findall(text)}


def _changelog_section_body(changelog: str, version: str) -> str | None:
    """Return the changelog body for a version heading."""
    match = re.search(
        rf"^##[ \t]+v{re.escape(version)}(?:[ \t]+.*)?$",
        changelog,
        re.MULTILINE,
    )
    if match is None:
        return None
    next_heading = re.search(r"^##\s+", changelog[match.end() :], re.MULTILINE)
    if next_heading is None:
        return changelog[match.end() :]
    return changelog[match.end() : match.end() + next_heading.start()]


def _check_stable_changelog_language(version: str, changelog: str) -> None:
    """Reject beta/prerelease terms in stable release sections."""
    if "-" in version:
        return
    section = _changelog_section_body(changelog, version)
    if section is None:
        return
    lower_section = section.lower()
    for term in STABLE_CHANGELOG_DISALLOWED_TERMS:
        if term in lower_section:
            _fail(
                "stable CHANGELOG section contains prerelease term "
                f"{term!r} in ## v{version}"
            )


def _entity_translation_keys(data: dict) -> dict[str, set[str]]:
    entity = data.get("entity")
    if not isinstance(entity, dict):
        _fail("translation file is missing the entity section")
    return {
        platform: set(platform_data)
        for platform, platform_data in entity.items()
        if isinstance(platform_data, dict)
    }


def _translation_structure(value: object) -> object:
    """Return recursive dict-key structure for translation parity checks."""
    if not isinstance(value, dict):
        return None
    return {
        str(key): _translation_structure(sub_value)
        for key, sub_value in sorted(value.items(), key=lambda item: str(item[0]))
    }


def check_manifest() -> str:
    manifest = _load_json(INTEGRATION / "manifest.json")
    required = {
        "domain": "stiebel_dhe_connect",
        "name": INTEGRATION_NAME,
        "categories": ["climate.water_heaters"],
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
    if hacs.get("name") != INTEGRATION_NAME:
        _fail("hacs.json name does not match the integration name")
    if hacs.get("homeassistant") != MIN_HOMEASSISTANT_VERSION:
        _fail(
            "hacs.json homeassistant minimum must match the validated support baseline "
            f"{MIN_HOMEASSISTANT_VERSION}"
        )
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
        "custom_components/stiebel_dhe_connect/brand/icon@2x.png",
        "docs/installation.md",
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
    _check_stable_changelog_language(version, changelog)
    if "## Documentation" not in readme:
        _fail("README is missing a Documentation section")
    readme_links = _markdown_link_targets(readme)
    missing_readme_doc_links = sorted(README_REQUIRED_DOC_LINKS - readme_links)
    if missing_readme_doc_links:
        _fail(
            "README is missing required documentation links: "
            + ", ".join(missing_readme_doc_links)
        )
    if "### Removal" not in readme:
        _fail("README is missing removal instructions")
    if (ROOT / "info.md").exists():
        _fail("legacy info.md release notes must not be restored; use CHANGELOG.md")


def check_lts_compatibility_policy() -> None:
    """Ensure documented LTS support boundaries match release-gate inputs."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    validation = (ROOT / "docs" / "validation.md").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    hacs = _load_json(ROOT / "hacs.json")

    expected_readme_line = (
        f"Minimum supported Home Assistant version: `{MIN_HOMEASSISTANT_VERSION}`"
    )
    if expected_readme_line not in readme:
        _fail("README minimum supported Home Assistant version is stale")
    check_requirement_includes(requirements)
    check_homeassistant_baseline()
    compatibility = read_baseline(ROOT / "requirements-ha-202610.txt")
    if (
        compatibility.version != Version(MIN_HOMEASSISTANT_VERSION)
        or compatibility.legacy_helpers_version is None
    ):
        _fail("compatibility baseline must pin the minimum HA version and matching legacy helpers")
    if hacs.get("homeassistant") != MIN_HOMEASSISTANT_VERSION:
        _fail("hacs.json Home Assistant minimum is stale")

    expected_validation_rows = (
        f"| Minimum supported Home Assistant version | `{MIN_HOMEASSISTANT_VERSION}` |",
        "| Baseline Home Assistant fixture | `requirements-ha.txt` (core and matching test helpers) |",
        f"| Python validation runtime | `{VALIDATION_PYTHON_VERSION}` |",
        "| Runtime dependency baseline | Supplied by the pinned Home Assistant core |",
        (
            "| Marketplace metadata | `hacs.json` declares "
            f"`homeassistant: {MIN_HOMEASSISTANT_VERSION}` |"
        ),
    )
    for row in expected_validation_rows:
        if row not in validation:
            _fail(f"docs/validation.md LTS matrix is missing or stale: {row}")
    for library in ("aiohttp", "probatio", "zeroconf"):
        if re.search(rf"^{library}\s*[<>=!~]", requirements, re.MULTILINE):
            _fail(f"requirements.txt must not duplicate Home Assistant's {library} pin")


def check_homeassistant_baseline() -> None:
    """Allow preview-to-stable pin updates without duplicating exact versions."""
    path = ROOT / "requirements-ha.txt"
    if not path.is_file():
        _fail("central Home Assistant baseline requirements-ha.txt is missing")
    requirements = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    series = NEXT_HOMEASSISTANT_SERIES
    if len(requirements) != 2 or not re.fullmatch(
        rf"homeassistant=={re.escape(series)}[.]\d+(?:(?:b|rc)\d+)?",
        requirements[0],
    ):
        _fail("central HA baseline must pin core in the supported release series")
    if not re.fullmatch(
        r"pytest-home-assistant @ git\+https://github[.]com/home-assistant/core[.]git@"
        r"[0-9a-f]{40}#subdirectory=packages/pytest-home-assistant",
        requirements[1],
    ):
        _fail("central HA test helpers must be pinned to a full core commit SHA")


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


def check_replay_fixtures() -> None:
    """Ensure replay fixtures stay inventory-safe and self-describing."""
    if not FIXTURE_ROOT.exists():
        _fail("tests/fixtures directory is missing")

    fixture_paths = sorted(FIXTURE_ROOT.glob(f"firmware_*/{REPLAY_FIXTURE_NAME}"))
    if not fixture_paths:
        _fail(f"no replay fixtures found at tests/fixtures/firmware_*/{REPLAY_FIXTURE_NAME}")

    stale_fixture_dirs = sorted(
        path
        for path in FIXTURE_ROOT.glob("firmware_*")
        if path.is_dir() and not (path / REPLAY_FIXTURE_NAME).exists()
    )
    if stale_fixture_dirs:
        stale = ", ".join(str(path.relative_to(ROOT)) for path in stale_fixture_dirs)
        _fail(f"replay fixture directories are missing {REPLAY_FIXTURE_NAME}: {stale}")

    for path in fixture_paths:
        fixture = _load_json(path)
        firmware_profile = path.parent.name
        if fixture.get("version") != 2:
            _fail(f"{path.relative_to(ROOT)} must have version=2")
        if fixture.get("firmware_profile") != firmware_profile:
            _fail(
                f"{path.relative_to(ROOT)} firmware_profile must match directory "
                f"name {firmware_profile!r}"
            )
        if not isinstance(fixture.get("socketio_packets"), list):
            _fail(f"{path.relative_to(ROOT)} must contain a socketio_packets list")
        if not isinstance(fixture.get("expected_runtime_state"), dict):
            _fail(
                f"{path.relative_to(ROOT)} must contain expected_runtime_state object"
            )


def check_github_actions() -> None:
    workflow = ROOT / ".github" / "workflows" / "validate.yml"
    if not workflow.exists():
        _fail("validation workflow is missing")
    text = workflow.read_text(encoding="utf-8")
    action_uses = _workflow_action_uses(text)
    if len(action_uses) != len(_USES_LINE_RE.findall(text)):
        _fail("every validation workflow action must use repository@ref syntax")
    action_refs = _workflow_action_refs(action_uses)
    refs_by_action: dict[str, list[str]] = {
        action: action_refs.get(action, []) for action in REQUIRED_VALIDATION_ACTIONS
    }

    unexpected = sorted(set(action_refs) - REQUIRED_VALIDATION_ACTIONS)
    if unexpected:
        _fail(f"validation workflow uses unapproved actions: {', '.join(unexpected)}")
    missing = sorted(
        action for action, refs in refs_by_action.items() if not refs
    )
    if missing:
        _fail(f"validation workflow is missing actions: {', '.join(missing)}")
    for action, refs in sorted(refs_by_action.items()):
        for ref in refs:
            if not re.fullmatch(r"[0-9a-f]{40}", ref):
                _fail(f"{action} must be pinned to a 40-character commit SHA")
        if len(set(refs)) != 1:
            _fail(f"all {action} uses must share the same commit SHA")
    for action, minimum_major in sorted(NODE24_VALIDATION_ACTION_MAJORS.items()):
        uses = [(ref, label) for name, ref, label in action_uses if name == action]
        for ref, label in uses:
            if not _action_ref_has_minimum_major(label or ref, minimum_major):
                _fail(
                    f"{action}@{ref} must have a v{minimum_major} or newer "
                    "release comment to avoid obsolete Node.js runtimes"
                )
    if "python scripts/check_deprecations.py" not in text:
        _fail("validation workflow must run scripts/check_deprecations.py")
    if "python scripts/check_privacy_markers.py" not in text:
        _fail("validation workflow must run scripts/check_privacy_markers.py")
    if "python scripts/check_translation_keys.py" not in text:
        _fail("validation workflow must run scripts/check_translation_keys.py")
    if "python scripts/check_release_consistency.py" not in text:
        _fail("validation workflow must run scripts/check_release_consistency.py")
    if f'python-version: "{VALIDATION_PYTHON_VERSION}"' not in text:
        _fail(
            "validation workflow Python version must match the documented "
            f"LTS runtime {VALIDATION_PYTHON_VERSION}"
        )
    if "cron: \"0 4 1 * *\"" not in text:
        _fail("validation workflow must keep monthly scheduled validation enabled")
    if "uses: hacs/action@" not in text:
        _fail("validation workflow must keep scheduled HACS validation enabled")
    if "uses: home-assistant/actions/hassfest@" not in text:
        _fail("validation workflow must keep scheduled Hassfest validation enabled")
    if "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'" not in text:
        _fail("latest Home Assistant drift check must run on schedule and workflow_dispatch")
    if "python scripts/ha_baseline.py --resolve-latest /tmp/requirements-ha-latest.txt" not in text:
        _fail("validation workflow must resolve a matching latest Home Assistant pair")
    if "python -m pip install --upgrade -r /tmp/requirements-ha-latest.txt" not in text:
        _fail("validation workflow must install the matching latest Home Assistant pair")
    if "python -m pip install -r requirements.txt" not in text:
        _fail("validation workflow must install requirements.txt")
    requirements_path = ROOT / "requirements.txt"
    if not requirements_path.exists():
        _fail("validation workflow installs requirements.txt but it is missing")
    check_requirement_includes(requirements_path.read_text(encoding="utf-8"))
    check_validation_dependencies((ROOT / "requirements-tools.txt").read_text(encoding="utf-8"))
    if (
        "--disable" + "-warnings" in text
        or "ignore::" + "DeprecationWarning" in text
    ):
        _fail("validation workflow must not suppress deprecation warnings")
    _check_workflow_execution(text, action_uses)


def _check_workflow_execution(text: str, action_uses: list[tuple[str, str, str | None]]) -> None:
    """Validate executable job/step structure, not strings in comments or names."""
    try:
        workflow = yaml.load(text, Loader=yaml.BaseLoader)
    except yaml.YAMLError:
        _fail("validation workflow must be valid YAML")
    if not isinstance(workflow, dict) or not isinstance(workflow.get("jobs"), dict):
        _fail("validation workflow must define jobs")
    triggers = workflow.get("on", {})
    if (
        not isinstance(triggers, dict)
        or not {"push", "pull_request", "workflow_dispatch", "schedule"} <= triggers.keys()
        or {"cron": "0 4 1 * *"} not in (triggers.get("schedule") or [])
    ):
        _fail("validation workflow must enable push, PR, dispatch and monthly schedule triggers")
    jobs = workflow["jobs"]
    actual_uses = []
    common_commands = (
        "python -m pip check",
        "python scripts/check_coverage.py",
        "python scripts/check_deprecations.py",
        "python scripts/check_privacy_markers.py",
        "python scripts/check_integration.py",
        "python scripts/check_translation_keys.py",
        "python scripts/check_release_consistency.py",
        "python scripts/check_typing.py",
        "python -m ruff check custom_components/stiebel_dhe_connect tests scripts",
    )
    for name in ("hacs", "hassfest", "repository", "home-assistant-compat", "home-assistant-latest"):
        job = jobs.get(name)
        if not isinstance(job, dict):
            _fail(f"validation workflow is missing job {name}")
        expected_condition = (
            "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'"
            if name == "home-assistant-latest" else None
        )
        if job.get("if") != expected_condition or job.get("continue-on-error", "false") != "false":
            _fail(f"{name}: validation job must run on its required events and fail on errors")
        steps = job.get("steps")
        if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
            _fail(f"{name}: validation steps must be a list of mappings")
        active_steps = [step for step in steps if "if" not in step and step.get("continue-on-error", "false") == "false"]
        for step in steps:
            if "uses" in step:
                actual_uses.append(step["uses"])
        active_uses = [step["uses"].split("@")[0] for step in active_steps if isinstance(step.get("uses"), str)]
        if "actions/checkout" not in active_uses:
            _fail(f"{name}: checkout must run unconditionally")
        if name in ("hacs", "hassfest"):
            required_action = "hacs/action" if name == "hacs" else "home-assistant/actions/hassfest"
            if required_action not in active_uses:
                _fail(f"{name}: required validation action must run unconditionally")
            continue
        if not any(
            step.get("uses", "").startswith("actions/setup-python@")
            and step.get("with", {}).get("python-version") == VALIDATION_PYTHON_VERSION
            for step in active_steps
        ):
            _fail(f"{name}: Python setup must use {VALIDATION_PYTHON_VERSION}")
        commands = []
        for step in active_steps:
            if isinstance(step.get("run"), str):
                try:
                    commands.append(shlex.split(step["run"], comments=True))
                except ValueError:
                    _fail(f"{name}: invalid shell command")
        required_commands = list(common_commands)
        if name == "home-assistant-compat":
            required_commands.extend((
                "python -m pip install -r requirements-ha-202610.txt -r requirements-tools.txt",
                "python scripts/ha_baseline.py --requirements requirements-ha-202610.txt",
                "python scripts/check_runtime_soak.py --cycles 30 --idle-seconds 60",
            ))
        else:
            required_commands.append("python -m pip install -r requirements.txt")
        if name == "repository":
            required_commands.append("python scripts/ha_baseline.py")
        elif name == "home-assistant-latest":
            required_commands.extend((
                "python scripts/ha_baseline.py --resolve-latest /tmp/requirements-ha-latest.txt",
                "python -m pip install --upgrade -r /tmp/requirements-ha-latest.txt",
                "python scripts/ha_baseline.py --requirements /tmp/requirements-ha-latest.txt",
                "python scripts/check_runtime_soak.py --cycles 30 --idle-seconds 60",
            ))
        for command in required_commands:
            if shlex.split(command) not in commands:
                _fail(f"{name}: missing unconditional command: {command}")
    if sorted(actual_uses) != sorted(f"{name}@{ref}" for name, ref, _ in action_uses):
        _fail("validation action pins must correspond to executable job steps")


def check_requirement_includes(text: str) -> None:
    """Keep the default environment limited to its HA pair and shared tools."""
    lines = [line.strip() for line in text.splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    expected = {"-r requirements-ha.txt", "-r requirements-tools.txt"}
    if len(lines) != len(expected) or set(lines) != expected:
        _fail("requirements.txt must contain only the HA baseline and shared-tools includes, once each")


def check_validation_dependencies(text: str) -> None:
    """Allow tool-floor updates inside reviewed bounds, not arbitrary upgrades."""
    requirements: dict[str, Requirement] = {}
    allowed_dependencies = set(VALIDATION_DEPENDENCY_MINIMUMS) | set(VALIDATION_TOOL_BOUNDS)
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            requirement = Requirement(line)
        except InvalidRequirement:
            _fail("requirements-tools.txt contains an invalid requirement")
        name = canonicalize_name(requirement.name)
        if name not in allowed_dependencies:
            _fail(f"requirements-tools.txt contains unreviewed direct dependency {name!r}")
        if name in requirements:
            _fail(f"requirements-tools.txt contains duplicate dependency {name!r}")
        if requirement.url or requirement.marker or requirement.extras:
            _fail(f"validation dependency {name!r} must be unconditional and from the index")
        requirements[name] = requirement
    for dependency, constraint in sorted(VALIDATION_DEPENDENCY_MINIMUMS.items()):
        requirement = requirements.get(dependency)
        if requirement is None or requirement.specifier != SpecifierSet(constraint):
            _fail(
                "validation workflow must install current dependency floor "
                f"{dependency + constraint!r}"
            )
    for dependency, (floor, ceiling) in sorted(VALIDATION_TOOL_BOUNDS.items()):
        requirement = requirements.get(dependency)
        specifiers = list(requirement.specifier) if requirement else []
        operators = {specifier.operator: specifier.version for specifier in specifiers}
        if len(specifiers) != 2 or set(operators) != {">=", "<"}:
            _fail(f"{dependency} must declare one >= floor and one < ceiling")
        try:
            lower, upper = Version(operators[">="]), Version(operators["<"])
        except InvalidVersion:
            _fail(f"{dependency} bounds must be valid stable versions")
        if (
            any(version.is_prerelease or version.local for version in (lower, upper))
            or not Version(floor) <= lower < upper <= Version(ceiling)
        ):
            _fail(f"{dependency} bounds must stay within >={floor},<{ceiling}")


def _workflow_action_uses(text: str) -> list[tuple[str, str, str | None]]:
    """Return action names, refs, and optional release comments from a workflow."""
    return [
        (action, ref, label or None)
        for action, ref, label in _ACTION_REF_RE.findall(text)
    ]


def _workflow_action_refs(
    action_uses: list[tuple[str, str, str | None]],
) -> dict[str, list[str]]:
    """Return workflow action refs grouped by action name."""
    refs: dict[str, list[str]] = {}
    for action, ref, _label in action_uses:
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
    en_structure = _translation_structure(en)
    de_structure = _translation_structure(de)
    if en_structure != de_structure:
        _fail("translation file structures differ between en.json and de.json")


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
    check_lts_compatibility_policy()
    check_gold_evidence_docs()
    check_quality_scale()
    check_replay_fixtures()
    check_github_actions()
    check_client_module_size()
    check_translations()
    check_type_gate_coverage()
    check_compile()
    check_unit_tests()
    print("integration checks ok")


if __name__ == "__main__":
    main()
