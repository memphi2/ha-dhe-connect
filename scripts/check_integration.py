"""Lightweight repository checks for the Stiebel DHE Connect integration."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "stiebel_dhe_connect"
TRANSLATIONS = INTEGRATION / "translations"


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


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
        "name": "Stiebel DHE Connect",
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
    if hacs.get("name") != "Stiebel DHE Connect":
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
        "custom_components/stiebel_dhe_connect/brand/icon.png",
    ):
        if not (ROOT / relative).exists():
            _fail(f"required file missing: {relative}")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"Current version: `{version}`" not in readme:
        _fail("README current version does not match manifest version")
    if f"## v{version}" not in changelog:
        _fail("CHANGELOG is missing a section for the manifest version")


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


def check_compile() -> None:
    for path in sorted(INTEGRATION.rglob("*.py")):
        try:
            source = path.read_text(encoding="utf-8")
            compile(source, str(path.relative_to(ROOT)), "exec")
        except SyntaxError as err:
            _fail(f"Python syntax check failed for {path.relative_to(ROOT)}: {err}")


def main() -> None:
    version = check_manifest()
    check_hacs()
    check_repository_files(version)
    check_translations()
    check_compile()
    print("integration checks ok")


if __name__ == "__main__":
    main()
