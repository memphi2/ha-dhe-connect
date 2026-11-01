"""Keep user guides, relative links and YAML examples usable."""

from __future__ import annotations

import ast
import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml
from homeassistant.components.homeassistant.triggers.state import TRIGGER_STATE_SCHEMA
from homeassistant.helpers import config_validation as cv

ROOT = Path(__file__).resolve().parents[1]
DOCS = (ROOT / "README.md", ROOT / "SECURITY.md", *sorted((ROOT / "docs").glob("*.md")))
YAML_BLOCK = re.compile(r"^```yaml[ \t]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^\s)]+)\)")


class _ImageSources(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            self.sources.extend(value for key, value in attrs if key == "src" and value)


def _yaml_examples():
    for path in DOCS:
        for index, match in enumerate(
            YAML_BLOCK.finditer(path.read_text(encoding="utf-8")), 1
        ):
            yield path, index, yaml.safe_load(match.group(1))


class DocumentationTests(unittest.TestCase):
    def test_security_reports_use_private_advisories(self):
        text = (ROOT / "SECURITY.md").read_text()
        self.assertIn("https://github.com/memphi2/ha-dhe-connect/security/advisories/new", text)
        self.assertIn("Ordinary bugs and feature requests", text)
        self.assertNotIn("report security-related issues through GitHub issues", text)

    def test_relative_document_and_image_links_exist(self):
        for path in DOCS:
            text = path.read_text(encoding="utf-8")
            images = _ImageSources()
            images.feed(text)
            for target in (*MARKDOWN_LINK.findall(text), *images.sources):
                url = urlsplit(target)
                if url.scheme or url.netloc or not url.path:
                    continue
                with self.subTest(document=str(path.relative_to(ROOT)), target=target):
                    self.assertTrue((path.parent / unquote(url.path)).exists())

    def test_user_installation_guides_use_marketplace_and_current_metadata(self):
        manifest = json.loads(
            (ROOT / "custom_components/stiebel_dhe_connect/manifest.json").read_text()
        )
        metadata = json.loads((ROOT / "hacs.json").read_text())
        for relative in ("README.md", "docs/installation.md", "docs/de.md"):
            with self.subTest(document=relative):
                text = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("Marketplace", text)
                self.assertIn(manifest["name"], text)
                self.assertIn(metadata["homeassistant"], text)
                self.assertNotIn("hacs_repository", text)
                self.assertNotIn("HACS (recommended)", text)
        installation = (ROOT / "docs/installation.md").read_text(encoding="utf-8")
        self.assertIn("`hacs.json`", installation)
        self.assertIn("## Existing Installations", installation)
        self.assertIn("## Updates", installation)
        self.assertIn("## Removal", installation)

    def test_yaml_examples_parse_as_structured_configuration(self):
        examples = list(_yaml_examples())
        self.assertGreater(len(examples), 5)
        for path, index, example in examples:
            with self.subTest(document=str(path.relative_to(ROOT)), block=index):
                self.assertIsInstance(example, (dict, list))

    def test_automation_state_triggers_use_ha_schema(self):
        count = 0
        for path, index, example in _yaml_examples():
            if not isinstance(example, dict) or "triggers" not in example:
                continue
            with self.subTest(document=str(path.relative_to(ROOT)), block=index):
                self.assertNotIn("for", example)
                self.assertIsInstance(example["actions"], list)
                cv.SCRIPT_SCHEMA(example["actions"])
                for trigger in example["triggers"]:
                    if trigger.get("trigger") == "state":
                        TRIGGER_STATE_SCHEMA(cv.TRIGGER_SCHEMA([trigger])[0])
                        count += 1
        self.assertGreater(count, 0)

    def test_offline_example_uses_a_real_error_state_and_trigger_duration(self):
        example = next(
            example
            for _, _, example in _yaml_examples()
            if isinstance(example, dict) and example.get("alias") == "DHE offline"
        )
        trigger = example["triggers"][0]
        self.assertEqual(trigger["entity_id"], "sensor.dhe_connect_error_status")
        self.assertEqual(trigger["for"], {"minutes": 2})
        module = ast.parse(
            (
                ROOT / "custom_components/stiebel_dhe_connect/sensor_diagnostics.py"
            ).read_text()
        )
        options = next(
            ast.literal_eval(node.value)
            for node in module.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "ERROR_STATUS_OPTIONS"
                for target in node.targets
            )
        )
        self.assertIn(trigger["to"], options)

    def test_countdown_example_matches_formatted_duration(self):
        from tests.test_entity_state_helpers import _load_entity_state_helpers

        helpers = _load_entity_state_helpers()
        example = next(
            example for _, _, example in _yaml_examples()
            if isinstance(example, dict)
            and example.get("alias") == "DHE shower countdown reaches zero"
        )
        trigger = example["triggers"][0]
        self.assertEqual(trigger["from"], helpers.format_minutes_duration(1 / 60))
        self.assertEqual(trigger["to"], helpers.format_minutes_duration(0))
        self.assertNotIn("conditions", example)

    def test_memory_docs_use_entity_actions(self):
        text = (ROOT / "docs/troubleshooting.md").read_text()
        for action in ("button.press", "number.set_value", "text.set_value"):
            self.assertIn(action, text)
        self.assertNotIn("memory services should include", text)
