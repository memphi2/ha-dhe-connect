"""Tests for lightweight repository checks."""

from __future__ import annotations

from contextlib import redirect_stderr
import json
from io import StringIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import check_integration  # noqa: E402

VALIDATION_INSTALL_STEPS = """
                  - run: python -m pip install -r requirements.txt
                  - run: python -m pip install --no-deps "pytest-homeassistant-custom-component>=0.13.335,<0.14"
"""
VALIDATION_REQUIREMENTS_TEXT = """
aiohttp>=3.13.5,<4
homeassistant==2026.6.0
mypy>=1.20,<2
pytest==9.0.3
pytest-cov==7.1.0
ruff>=0.15,<0.16
"""


def _write_validate_workflow(root: Path, content: str) -> None:
    path = root / ".github" / "workflows" / "validate.yml"
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    (root / "requirements.txt").write_text(VALIDATION_REQUIREMENTS_TEXT, encoding="utf-8")


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
    (integration / "brand" / "logo.png").write_bytes(b"png")

    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    for name in (
        "troubleshooting.md",
        "validation.md",
        "examples.md",
        "use-cases.md",
        "known_limitations.md",
        "legal.md",
    ):
        (docs / name).write_text(f"# {name}\n", encoding="utf-8")

    (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (root / "hacs.json").write_text('{"name":"DHE Connect","render_readme":true}\n', encoding="utf-8")
    (root / "README.md").write_text(
        (
            "# README\n\n"
            f"Current version: `{version}`\n\n"
            "### Removal\n\n"
            "## Documentation\n\n"
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


class TestCheckIntegration(unittest.TestCase):
    """Validate repository guard helpers."""

    def test_github_actions_accepts_pinned_validation_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_validate_workflow(
                root,
                """
                steps:
                  - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
                  - uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405
                  - uses: hacs/action@dcb30e72781db3f207d5236b861172774ab0b485
                  - uses: home-assistant/actions/hassfest@f6f29a7ee3fa0eccadf3620a7b9ee00ab54ec03b
                  - run: python -m pip install -r requirements.txt
                  - run: python -m pip install --no-deps "pytest-homeassistant-custom-component>=0.13.335,<0.14"
                  - run: python scripts/check_deprecations.py
                  - run: python scripts/check_privacy_markers.py
                  - run: python scripts/check_translation_keys.py
                  - run: python scripts/check_release_consistency.py
                """,
            )

            with patch.object(check_integration, "ROOT", root):
                check_integration.check_github_actions()

    def test_github_actions_requires_deprecation_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_validate_workflow(
                root,
                """
                steps:
                  - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
                  - uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405
                  - uses: hacs/action@dcb30e72781db3f207d5236b861172774ab0b485
                  - uses: home-assistant/actions/hassfest@f6f29a7ee3fa0eccadf3620a7b9ee00ab54ec03b
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
                  - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
                  - uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405
                  - uses: hacs/action@dcb30e72781db3f207d5236b861172774ab0b485
                  - uses: home-assistant/actions/hassfest@f6f29a7ee3fa0eccadf3620a7b9ee00ab54ec03b
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
                  - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
                  - uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405
                  - uses: hacs/action@dcb30e72781db3f207d5236b861172774ab0b485
                  - uses: home-assistant/actions/hassfest@f6f29a7ee3fa0eccadf3620a7b9ee00ab54ec03b
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

    def test_github_actions_requires_fixture_helper_no_deps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_validate_workflow(
                root,
                """
                steps:
                  - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
                  - uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405
                  - uses: hacs/action@dcb30e72781db3f207d5236b861172774ab0b485
                  - uses: home-assistant/actions/hassfest@f6f29a7ee3fa0eccadf3620a7b9ee00ab54ec03b
                  - run: python -m pip install -r requirements.txt
                  - run: python -m pip install "pytest-homeassistant-custom-component>=0.13.335,<0.14"
                  - run: python scripts/check_deprecations.py
                  - run: python scripts/check_privacy_markers.py
                  - run: python scripts/check_translation_keys.py
                  - run: python scripts/check_release_consistency.py
                """,
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
                  - uses: hacs/action@dcb30e72781db3f207d5236b861172774ab0b485
                  - uses: home-assistant/actions/hassfest@f6f29a7ee3fa0eccadf3620a7b9ee00ab54ec03b
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
                  - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
                  - uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405
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
                  - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
                  - uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405
                  - uses: hacs/action@main
                  - uses: hacs/action@dcb30e72781db3f207d5236b861172774ab0b485
                  - uses: home-assistant/actions/hassfest@f6f29a7ee3fa0eccadf3620a7b9ee00ab54ec03b
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


if __name__ == "__main__":
    unittest.main()
