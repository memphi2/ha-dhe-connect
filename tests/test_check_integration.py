"""Tests for lightweight repository checks."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import check_integration


class TestUnitTestEntryPoint(unittest.TestCase):
    def test_direct_script_exposes_shared_test_support_modules(self):
        with (
            patch.object(sys, "path", []),
            patch.object(unittest.defaultTestLoader, "discover") as discover,
            patch.object(unittest, "TextTestRunner") as runner,
        ):
            check_integration.check_unit_tests()
            self.assertEqual(sys.path[0], str(ROOT))
            discover.assert_called_once_with(str(ROOT / "tests"))
            runner.return_value.run.assert_called_once_with(discover.return_value)

VALIDATION_INSTALL_STEPS = """
	                  - run: python -m pip install -r requirements.txt
"""
VALIDATION_REQUIREMENTS_TEXT = """
mypy>=2.4,<3
pytest-cov>=7.1,<8
ruff>=0.17,<0.18
"""
VALIDATION_INCLUDES_TEXT = "-r requirements-ha.txt\n-r requirements-tools.txt\n"
COMPAT_HA_REQUIREMENTS_TEXT = (
    "homeassistant==2026.10.4\npytest-homeassistant-custom-component==0.13.375\n"
)
VALIDATION_HA_REQUIREMENTS_TEXT = (
    "homeassistant==2026.11.0b1\n"
    "pytest-home-assistant @ git+https://github.com/home-assistant/core.git@"
    "6cfd47af9851a1552ad6f58c926b5814689a9f1d"
    "#subdirectory=packages/pytest-home-assistant\n"
)


def _write_validate_workflow(root: Path, content: str) -> None:
    path = root / ".github" / "workflows" / "validate.yml"
    path.parent.mkdir(parents=True)
    path.write_text(
        (
            "on:\n"
            "  schedule:\n"
            "    - cron: \"0 4 1 * *\"\n"
            "  workflow_dispatch:\n\n"
            + content
            if "jobs:" not in content else content
        ),
        encoding="utf-8",
    )
    (root / "requirements.txt").write_text(VALIDATION_INCLUDES_TEXT, encoding="utf-8")
    (root / "requirements-tools.txt").write_text(VALIDATION_REQUIREMENTS_TEXT, encoding="utf-8")
    (root / "requirements-ha.txt").write_text(
        VALIDATION_HA_REQUIREMENTS_TEXT, encoding="utf-8"
    )


def _write_type_gate_fixture(root: Path, files: list[str]) -> None:
    integration = root / "custom_components" / "stiebel_dhe_connect"
    integration.mkdir(parents=True)
    for name in ("__init__.py", "client.py", "config_flow_scan_state.py"):
        (integration / name).write_text("", encoding="utf-8")
    quoted_files = "\n".join(f'    "{file}",' for file in files)
    (root / "pyproject.toml").write_text(
        "[tool.mypy]\nfiles = [\n" + quoted_files + "\n]\n",
        encoding="utf-8",
    )


def _write_replay_fixture(root: Path, profile: str, *, version: int = 2) -> None:
    fixture_path = (
        root / "tests" / "fixtures" / profile / "dhe_protocol_replay_sanitized.json"
    )
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(
        json.dumps(
            {
                "version": version,
                "firmware_profile": profile,
                "engineio_open": "0{\"sid\":\"fixture\"}",
                "socketio_packets": [{"packet": "42[\"message\",{}]"}],
                "expected_runtime_state": {},
            }
        ),
        encoding="utf-8",
    )


def _write_repository_files_fixture(
    root: Path,
    *,
    version: str = "1.3.2",
    changelog_section_text: str = "Stable release.",
) -> None:
    integration = root / "custom_components" / "stiebel_dhe_connect"
    (integration / "brand").mkdir(parents=True, exist_ok=True)
    (integration / "services.yaml").write_text("{}", encoding="utf-8")
    (integration / "quality_scale.yaml").write_text("rules: {}\n", encoding="utf-8")
    (integration / "brand" / "icon.png").write_bytes(b"png")
    (integration / "brand" / "icon@2x.png").write_bytes(b"png")

    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    for name in (
        "installation.md",
        "troubleshooting.md",
        "validation.md",
        "examples.md",
        "use-cases.md",
        "known_limitations.md",
        "legal.md",
    ):
        (docs / name).write_text(f"# {name}\n", encoding="utf-8")

    (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (root / "hacs.json").write_text(
        json.dumps({"name": check_integration.INTEGRATION_NAME, "render_readme": True}),
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        (
            "# README\n\n"
            f"Current version: `{version}`\n\n"
            "### Removal\n\n"
            "## Documentation\n\n"
            "- [Installation and updates](docs/installation.md)\n"
            "- [Troubleshooting guide](docs/troubleshooting.md)\n"
            "- [Examples](docs/examples.md)\n"
            "- [Use cases](docs/use-cases.md)\n"
            "- [Known limitations](docs/known_limitations.md)\n"
            "- [Legal notes](docs/legal.md)\n"
        ),
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text(
        (
            "# Changelog\n\n"
            "## Unreleased\n\n"
            "- No changes yet.\n\n"
            f"## v{version}\n\n"
            f"{changelog_section_text}\n"
        ),
        encoding="utf-8",
    )


def _write_lts_policy_fixture(root: Path) -> None:
    version = check_integration.MIN_HOMEASSISTANT_VERSION
    python_version = check_integration.VALIDATION_PYTHON_VERSION
    (root / "README.md").write_text(
        (
            "# README\n\n"
            f"- Minimum supported Home Assistant version: `{version}`\n"
        ),
        encoding="utf-8",
    )
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "validation.md").write_text(
        (
            "# Validation\n\n"
            "## LTS Compatibility Matrix\n\n"
            "| Surface | Current release gate |\n"
            "|---|---|\n"
            f"| Minimum supported Home Assistant version | `{version}` |\n"
            "| Baseline Home Assistant fixture | `requirements-ha.txt` (core and matching test helpers) |\n"
            f"| Python validation runtime | `{python_version}` |\n"
            "| Runtime dependency baseline | Supplied by the pinned Home Assistant core |\n"
            f"| Marketplace metadata | `hacs.json` declares `homeassistant: {version}` |\n"
        ),
        encoding="utf-8",
    )
    (root / "requirements.txt").write_text(
        VALIDATION_INCLUDES_TEXT,
        encoding="utf-8",
    )
    (root / "requirements-ha-202610.txt").write_text(
        COMPAT_HA_REQUIREMENTS_TEXT, encoding="utf-8"
    )
    (root / "requirements-ha.txt").write_text(
        VALIDATION_HA_REQUIREMENTS_TEXT, encoding="utf-8"
    )
    (root / "hacs.json").write_text(
        json.dumps(
            {
                "name": check_integration.INTEGRATION_NAME,
                "homeassistant": version,
                "render_readme": True,
            }
        ),
        encoding="utf-8",
    )


class TestCheckIntegration(unittest.TestCase):
    """Validate repository guard helpers."""

    def test_manifest_requires_device_category_not_entity_domains(self) -> None:
        manifest = {
            "domain": "stiebel_dhe_connect",
            "name": check_integration.INTEGRATION_NAME,
            "categories": ["climate.water_heaters"],
            "config_flow": True,
            "iot_class": "local_push",
            "integration_type": "device",
            "requirements": [],
            "version": "2.0.10",
        }
        with patch.object(check_integration, "_load_json", return_value=manifest):
            self.assertEqual(check_integration.check_manifest(), manifest["version"])
            for categories in (None, [], "climate.water_heaters", ["Climate"], ["sensor"]):
                with self.subTest(categories=categories), redirect_stderr(StringIO()):
                    manifest["categories"] = categories
                    with self.assertRaises(SystemExit):
                        check_integration.check_manifest()

    def test_ha_baseline_accepts_preview_and_stable_without_other_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for version in ("2026.11.0b1", "2026.11.0rc1", "2026.11.0", "2026.11.4"):
                with self.subTest(version=version):
                    (root / "requirements-ha.txt").write_text(
                        VALIDATION_HA_REQUIREMENTS_TEXT.replace("2026.11.0b1", version),
                        encoding="utf-8",
                    )
                    with patch.object(check_integration, "ROOT", root):
                        check_integration.check_homeassistant_baseline()

    def test_ha_baseline_rejects_old_series_and_floating_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for bad in (
                VALIDATION_HA_REQUIREMENTS_TEXT.replace("2026.11.0b1", "2026.10.4"),
                VALIDATION_HA_REQUIREMENTS_TEXT.replace("2026.11.0b1", "2026.12.0"),
                VALIDATION_HA_REQUIREMENTS_TEXT.replace(
                    "6cfd47af9851a1552ad6f58c926b5814689a9f1d", "dev"
                ),
            ):
                with self.subTest(requirements=bad):
                    (root / "requirements-ha.txt").write_text(bad, encoding="utf-8")
                    with (
                        patch.object(check_integration, "ROOT", root),
                        redirect_stderr(StringIO()), self.assertRaises(SystemExit),
                    ):
                        check_integration.check_homeassistant_baseline()

    def test_validation_tool_floor_updates_within_supported_bounds(self) -> None:
        for dependency, versions in (
            ("mypy", (">=2.4.1,<3", ">=2.5,<3", ">=2.4.1,<2.5", "<3.0,>=2.4.1")),
            ("ruff", (">=0.17.3,<0.18", "<0.18, >=0.17.3")),
        ):
            original = next(line for line in VALIDATION_REQUIREMENTS_TEXT.splitlines()
                            if line.startswith(dependency))
            for version in versions:
                with self.subTest(dependency=dependency, version=version):
                    check_integration.check_validation_dependencies(
                        VALIDATION_REQUIREMENTS_TEXT.replace(original, dependency + version)
                    )

    def test_validation_tool_bounds_reject_unsafe_or_conditional_requirements(self) -> None:
        for invalid in (
            "mypy>=2.3,<3", "mypy>=2.4,<4", "mypy>=2.4", "mypy==2.4.1",
            "mypy>=3,<3", "mypy>=2.4rc1,<3", "mypy>=2.4,<3rc1",
            "mypy>=2.4+local,<3", "mypy>=2.4,<3; python_version<'3.14'",
            "mypy[extra]>=2.4,<3", "mypy @ https://example.com/mypy.whl",
            "mypy>=2.4,<3,!=2.4.1", "# mypy>=2.4,<3", "not a requirement",
        ):
            with (
                self.subTest(invalid=invalid),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit),
            ):
                check_integration.check_validation_dependencies(
                    VALIDATION_REQUIREMENTS_TEXT.replace("mypy>=2.4,<3", invalid)
                )

    def test_validation_dependencies_reject_duplicates_and_comment_only_pins(self) -> None:
        for text in (
            VALIDATION_REQUIREMENTS_TEXT + "mypy>=2.4.1,<3\n",
            VALIDATION_REQUIREMENTS_TEXT.replace("pytest-cov>=7.1,<8", "# pytest-cov>=7.1,<8"),
        ):
            with (
                self.subTest(text=text),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit),
            ):
                check_integration.check_validation_dependencies(text)

    def test_validation_dependencies_reject_unreviewed_direct_requirements(self) -> None:
        for dependency in (
            "aiohttp>=3.14,<4", "probatio==0.13.0", "zeroconf==0.151.5",
            "pytest==9.0.3", "homeassistant==2026.11.0",
            "pytest-homeassistant-custom-component==0.13.372", "requests",
            "AIOHTTP", "pytest_home_assistant",
        ):
            with (
                self.subTest(dependency=dependency),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit),
            ):
                check_integration.check_validation_dependencies(
                    VALIDATION_REQUIREMENTS_TEXT + dependency + "\n"
                )

    def test_validation_dependencies_require_only_the_central_baseline_include(self) -> None:
        for include in (
            "", "# -r requirements-ha.txt", "-r unreviewed.txt",
            "-r requirements-ha.txt\n-r unreviewed.txt",
            "-r requirements-ha.txt\n-r requirements-ha.txt",
            "-r requirements-ha.txt\n-c constraints.txt",
            "-r requirements-ha.txt\n--requirement=unreviewed.txt",
        ):
            with (
                self.subTest(include=include),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit),
            ):
                check_integration.check_requirement_includes(
                    VALIDATION_INCLUDES_TEXT.replace("-r requirements-ha.txt", include)
                )

    def test_dependabot_keeps_quarterly_grouped_version_updates(self) -> None:
        config = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text(encoding="utf-8"))
        self.assertEqual(config["version"], 2)
        self.assertEqual(len(config["updates"]), 2)
        updates = {entry["package-ecosystem"]: entry for entry in config["updates"]}
        self.assertEqual(set(updates), {"github-actions", "pip"})
        for ecosystem, entry in updates.items():
            with self.subTest(ecosystem=ecosystem):
                self.assertEqual(entry["directory"], "/")
                self.assertEqual(entry["schedule"]["interval"], "quarterly")
                self.assertNotIn("day", entry["schedule"])
                self.assertEqual(entry["open-pull-requests-limit"], 1)
                self.assertNotIn("target-branch", entry)
                groups = list(entry["groups"].values())
                self.assertEqual(len(groups), 1)
                self.assertEqual(groups[0]["applies-to"], "version-updates")
                self.assertEqual(groups[0]["patterns"], ["*"])
                for ignored in entry.get("ignore", []):
                    self.assertNotIn("versions", ignored)
                    self.assertTrue(ignored.get("update-types"))
        python_group = next(iter(updates["pip"]["groups"].values()))
        self.assertEqual(set(python_group["update-types"]), {"minor", "patch"})

    def test_validation_ruff_bounds_do_not_allow_unsupported_minor(self) -> None:
        for invalid in (">=0.16,<0.18", ">=0.17,<0.19", ">=0.17.3", ">=0.18,<0.18"):
            with (
                self.subTest(invalid=invalid),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit),
            ):
                check_integration.check_validation_dependencies(
                    VALIDATION_REQUIREMENTS_TEXT.replace("ruff>=0.17,<0.18", "ruff" + invalid)
                )

    def test_github_actions_accepts_pinned_validation_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_validate_workflow(
                root,
                (ROOT / ".github/workflows/validate.yml").read_text(encoding="utf-8"),
            )

            with patch.object(check_integration, "ROOT", root):
                check_integration.check_github_actions()

    def test_workflow_guards_require_executable_checks_in_each_test_job(self) -> None:
        original = (ROOT / ".github/workflows/validate.yml").read_text(encoding="utf-8")
        for job in ("repository", "home-assistant-compat", "home-assistant-latest"):
            for command in ("python scripts/check_coverage.py", "python -m pip check"):
                for replacement in (f"run: true # {command}", f"if: false\n        run: {command}", f"continue-on-error: true\n        run: {command}"):
                    with self.subTest(job=job, command=command, replacement=replacement), tempfile.TemporaryDirectory() as temp_dir:
                        root = Path(temp_dir)
                        before, after = original.split(f"  {job}:", 1)
                        modified = before + f"  {job}:" + after.replace(f"run: {command}", replacement, 1)
                        _write_validate_workflow(root, modified)
                        with patch.object(check_integration, "ROOT", root), redirect_stderr(StringIO()), self.assertRaisesRegex(SystemExit, "1"):
                            check_integration.check_github_actions()

    def test_workflow_requires_baseline_verification_and_active_jobs(self) -> None:
        original = (ROOT / ".github/workflows/validate.yml").read_text(encoding="utf-8")
        for old, new in (
            ("run: python scripts/ha_baseline.py\n", "run: true # python scripts/ha_baseline.py\n"),
            ("run: python scripts/ha_baseline.py --requirements", "run: echo python scripts/ha_baseline.py --requirements"),
            ("  repository:\n", "  repository:\n    if: false\n"),
            ("  hacs:\n", "  hacs:\n    if: false\n"),
            ("  hassfest:\n", "  hassfest:\n    continue-on-error: true\n"),
            ("  push:\n", "  # push:\n"),
        ):
            with self.subTest(old=old), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                _write_validate_workflow(root, original.replace(old, new, 1))
                with patch.object(check_integration, "ROOT", root), redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                    check_integration.check_github_actions()

    def test_github_actions_rejects_unapproved_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_validate_workflow(
                root,
                """
                steps:
                  - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
                  - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
                  - uses: hacs/action@1ebf01c408f29afcb6406bd431bc98fd8cbb15aa
                  - uses: home-assistant/actions/hassfest@50baf3a307f87100cf550d4ae127746595030d5d
                  - uses: example/unapproved@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
                """,
            )

            with patch.object(check_integration, "ROOT", root), redirect_stderr(
                StringIO()
            ), self.assertRaises(SystemExit):
                check_integration.check_github_actions()

    def test_github_actions_rejects_inconsistent_action_pins(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_validate_workflow(
                root,
                """
                steps:
                  - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
                  - uses: actions/checkout@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa # v7.0.1
                  - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
                  - uses: hacs/action@1ebf01c408f29afcb6406bd431bc98fd8cbb15aa
                  - uses: home-assistant/actions/hassfest@50baf3a307f87100cf550d4ae127746595030d5d
                """,
            )

            with patch.object(check_integration, "ROOT", root), redirect_stderr(
                StringIO()
            ), self.assertRaises(SystemExit):
                check_integration.check_github_actions()

    def test_github_actions_rejects_obsolete_action_release_comment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_validate_workflow(
                root,
                """
                steps:
                  - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
                  - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v6.9.0
                  - uses: hacs/action@1ebf01c408f29afcb6406bd431bc98fd8cbb15aa
                  - uses: home-assistant/actions/hassfest@50baf3a307f87100cf550d4ae127746595030d5d
                """,
            )

            with patch.object(check_integration, "ROOT", root), redirect_stderr(
                StringIO()
            ), self.assertRaises(SystemExit):
                check_integration.check_github_actions()

    def test_github_actions_requires_deprecation_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_validate_workflow(
                root,
                """
                steps:
                  - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
                  - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
                  - uses: hacs/action@1ebf01c408f29afcb6406bd431bc98fd8cbb15aa
                  - uses: home-assistant/actions/hassfest@50baf3a307f87100cf550d4ae127746595030d5d
""" + VALIDATION_INSTALL_STEPS + """
                """,
            )

            with patch.object(check_integration, "ROOT", root), redirect_stderr(
                StringIO()
            ), self.assertRaises(SystemExit):
                check_integration.check_github_actions()

    def test_github_actions_requires_privacy_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_validate_workflow(
                root,
                """
                steps:
                  - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
                  - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
                  - uses: hacs/action@1ebf01c408f29afcb6406bd431bc98fd8cbb15aa
                  - uses: home-assistant/actions/hassfest@50baf3a307f87100cf550d4ae127746595030d5d
""" + VALIDATION_INSTALL_STEPS + """
                  - run: python scripts/check_deprecations.py
                  - run: python scripts/check_release_consistency.py
                """,
            )

            with patch.object(check_integration, "ROOT", root), redirect_stderr(
                StringIO()
            ), self.assertRaises(SystemExit):
                check_integration.check_github_actions()

    def test_github_actions_requires_translation_key_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_validate_workflow(
                root,
                """
                steps:
                  - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
                  - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
                  - uses: hacs/action@1ebf01c408f29afcb6406bd431bc98fd8cbb15aa
                  - uses: home-assistant/actions/hassfest@50baf3a307f87100cf550d4ae127746595030d5d
""" + VALIDATION_INSTALL_STEPS + """
                  - run: python scripts/check_deprecations.py
                  - run: python scripts/check_privacy_markers.py
                  - run: python scripts/check_release_consistency.py
                """,
            )

            with patch.object(check_integration, "ROOT", root), redirect_stderr(
                StringIO()
            ), self.assertRaises(SystemExit):
                check_integration.check_github_actions()

    def test_github_actions_rejects_stale_tool_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_validate_workflow(
                root,
                """
                steps:
                  - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
                  - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
                  - uses: hacs/action@1ebf01c408f29afcb6406bd431bc98fd8cbb15aa
                  - uses: home-assistant/actions/hassfest@50baf3a307f87100cf550d4ae127746595030d5d
                  - run: python -m pip install -r requirements.txt
                  - run: python scripts/check_deprecations.py
                  - run: python scripts/check_privacy_markers.py
                  - run: python scripts/check_translation_keys.py
                  - run: python scripts/check_release_consistency.py
                """,
            )
            requirements = root / "requirements-tools.txt"
            requirements.write_text(
                requirements.read_text(encoding="utf-8").replace(
                    "mypy>=2.4,<3",
                    "mypy>=2.3,<3",
                ),
                encoding="utf-8",
            )

            with patch.object(check_integration, "ROOT", root), redirect_stderr(
                StringIO()
            ), self.assertRaises(SystemExit):
                check_integration.check_github_actions()

    def test_github_actions_rejects_node20_action_refs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_validate_workflow(
                root,
                """
                steps:
                  - uses: actions/checkout@v4
                  - uses: actions/setup-python@v5
                  - uses: hacs/action@1ebf01c408f29afcb6406bd431bc98fd8cbb15aa
                  - uses: home-assistant/actions/hassfest@50baf3a307f87100cf550d4ae127746595030d5d
                """,
            )

            with patch.object(check_integration, "ROOT", root), redirect_stderr(
                StringIO()
            ), self.assertRaises(SystemExit):
                check_integration.check_github_actions()

    def test_github_actions_rejects_floating_validation_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_validate_workflow(
                root,
                """
                steps:
                  - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
                  - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
                  - uses: hacs/action@main
                  - uses: home-assistant/actions/hassfest@master
                """,
            )

            with patch.object(check_integration, "ROOT", root), redirect_stderr(
                StringIO()
            ), self.assertRaises(SystemExit):
                check_integration.check_github_actions()

    def test_github_actions_rejects_duplicate_action_with_one_floating_ref(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_validate_workflow(
                root,
                """
                steps:
                  - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
                  - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
                  - uses: hacs/action@main
                  - uses: hacs/action@1ebf01c408f29afcb6406bd431bc98fd8cbb15aa
                  - uses: home-assistant/actions/hassfest@50baf3a307f87100cf550d4ae127746595030d5d
                """,
            )

            with patch.object(check_integration, "ROOT", root), redirect_stderr(
                StringIO()
            ), self.assertRaises(SystemExit):
                check_integration.check_github_actions()

    def test_type_gate_coverage_accepts_all_integration_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            integration = root / "custom_components" / "stiebel_dhe_connect"
            files = [
                "custom_components/stiebel_dhe_connect/__init__.py",
                "custom_components/stiebel_dhe_connect/client.py",
                "custom_components/stiebel_dhe_connect/config_flow_scan_state.py",
            ]
            _write_type_gate_fixture(root, files)

            with (
                patch.object(check_integration, "ROOT", root),
                patch.object(check_integration, "INTEGRATION", integration),
            ):
                check_integration.check_type_gate_coverage()

    def test_type_gate_coverage_rejects_missing_integration_module(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            integration = root / "custom_components" / "stiebel_dhe_connect"
            _write_type_gate_fixture(
                root,
                [
                    "custom_components/stiebel_dhe_connect/__init__.py",
                    "custom_components/stiebel_dhe_connect/client.py",
                ],
            )

            with (
                patch.object(check_integration, "ROOT", root),
                patch.object(check_integration, "INTEGRATION", integration),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit),
            ):
                check_integration.check_type_gate_coverage()

    def test_type_gate_coverage_rejects_stale_integration_module(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            integration = root / "custom_components" / "stiebel_dhe_connect"
            _write_type_gate_fixture(
                root,
                [
                    "custom_components/stiebel_dhe_connect/__init__.py",
                    "custom_components/stiebel_dhe_connect/client.py",
                    "custom_components/stiebel_dhe_connect/config_flow_scan_state.py",
                    "custom_components/stiebel_dhe_connect/deleted_module.py",
                ],
            )

            with (
                patch.object(check_integration, "ROOT", root),
                patch.object(check_integration, "INTEGRATION", integration),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit),
            ):
                check_integration.check_type_gate_coverage()

    def test_replay_fixture_inventory_accepts_valid_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_replay_fixture(root, "firmware_a")
            _write_replay_fixture(root, "firmware_b")

            with (
                patch.object(check_integration, "ROOT", root),
                patch.object(check_integration, "FIXTURE_ROOT", root / "tests" / "fixtures"),
            ):
                check_integration.check_replay_fixtures()

    def test_replay_fixture_inventory_rejects_stale_firmware_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_replay_fixture(root, "firmware_a")
            (root / "tests" / "fixtures" / "firmware_b").mkdir(parents=True, exist_ok=True)

            with (
                patch.object(check_integration, "ROOT", root),
                patch.object(check_integration, "FIXTURE_ROOT", root / "tests" / "fixtures"),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit),
            ):
                check_integration.check_replay_fixtures()

    def test_check_translations_rejects_structure_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            integration = root / "custom_components" / "stiebel_dhe_connect" / "translations"
            integration.mkdir(parents=True, exist_ok=True)
            (integration / "en.json").write_text(
                json.dumps(
                    {
                        "entity": {"sensor": {"one": {"name": "One"}}},
                        "config": {"error": {"cannot_connect": "x"}},
                    }
                ),
                encoding="utf-8",
            )
            (integration / "de.json").write_text(
                json.dumps(
                    {
                        "entity": {"sensor": {"one": {"name": "Eins"}}},
                        "config": {"error": {"cannot_connect": "x", "invalid_host": "y"}},
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.object(check_integration, "TRANSLATIONS", integration),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit),
            ):
                check_integration.check_translations()

    def test_repository_files_accepts_required_doc_links_with_custom_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_repository_files_fixture(root)

            with patch.object(check_integration, "ROOT", root):
                check_integration.check_repository_files("1.3.2")

    def test_repository_files_rejects_prerelease_terms_for_stable_release(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_repository_files_fixture(
                root,
                changelog_section_text=(
                    "Stable release.\n\n"
                    "Contains beta compatibility notes."
                ),
            )

            with (
                patch.object(check_integration, "ROOT", root),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit),
            ):
                check_integration.check_repository_files("1.3.2")

    def test_hacs_accepts_declared_minimum_homeassistant_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "hacs.json").write_text(
                json.dumps(
                    {
                        "name": check_integration.INTEGRATION_NAME,
                        "homeassistant": check_integration.MIN_HOMEASSISTANT_VERSION,
                        "render_readme": True,
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(check_integration, "ROOT", root):
                check_integration.check_hacs()

    def test_hacs_rejects_stale_minimum_homeassistant_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "hacs.json").write_text(
                json.dumps(
                    {
                        "name": check_integration.INTEGRATION_NAME,
                        "homeassistant": "2026.5.0",
                        "render_readme": True,
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.object(check_integration, "ROOT", root),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit),
            ):
                check_integration.check_hacs()

    def test_lts_policy_accepts_matching_support_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_lts_policy_fixture(root)

            with patch.object(check_integration, "ROOT", root):
                check_integration.check_lts_compatibility_policy()

    def test_lts_policy_rejects_duplicated_ha_runtime_pins(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for library in ("aiohttp", "probatio", "zeroconf"):
                with self.subTest(library=library):
                    _write_lts_policy_fixture(root)
                    (root / "requirements.txt").write_text(
                        f"-r requirements-ha.txt\n{library}==0.0.0\n",
                        encoding="utf-8",
                    )
                    stderr = StringIO()
                    with (
                        patch.object(check_integration, "ROOT", root),
                        redirect_stderr(stderr), self.assertRaises(SystemExit),
                    ):
                        check_integration.check_lts_compatibility_policy()
                    self.assertIn("must contain only", stderr.getvalue())

    def test_lts_policy_rejects_stale_readme_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_lts_policy_fixture(root)
            (root / "README.md").write_text(
                "- Minimum supported Home Assistant version: `2026.5.0`\n",
                encoding="utf-8",
            )

            with (
                patch.object(check_integration, "ROOT", root),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit),
            ):
                check_integration.check_lts_compatibility_policy()

    def test_lts_policy_rejects_stale_validation_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_lts_policy_fixture(root)
            validation = root / "docs" / "validation.md"
            validation.write_text(
                validation.read_text(encoding="utf-8").replace(
                    "`requirements-ha.txt`",
                    "`outdated-requirements.txt`",
                ),
                encoding="utf-8",
            )

            with (
                patch.object(check_integration, "ROOT", root),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit),
            ):
                check_integration.check_lts_compatibility_policy()


if __name__ == "__main__":
    unittest.main()
