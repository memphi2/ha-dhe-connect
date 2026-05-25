"""Validate required user-facing translation keys for flows, repairs and services."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Final


ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS = ROOT / "custom_components" / "stiebel_dhe_connect" / "translations"
LOCALES: Final[tuple[str, ...]] = ("en", "de")

REQUIRED_KEYS: Final[dict[str, dict[str, set[str]]]] = {
    "config.error": {
        "all": {
            "cannot_connect",
            "invalid_internal_scald_protection",
            "invalid_port",
            "invalid_setup_mode",
        }
    },
    "config.abort": {
        "all": {
            "already_configured",
            "invalid_discovery_parameters",
            "conflicting_discovery_identity",
            "low_confidence_discovery",
        }
    },
    "options.error": {
        "all": {
            "cannot_connect",
            "device_settings_failed",
            "not_loaded",
        }
    },
    "issues.pairing_required.fix_flow.abort": {
        "all": {
            "entry_not_found",
            "invalid_entry",
        }
    },
    "issues.token_invalid.fix_flow.abort": {
        "all": {
            "entry_not_found",
            "invalid_entry",
        }
    },
    "issues": {
        "all": {
            "pairing_required",
            "token_invalid",
            "device_unreachable",
            "discovery_conflict",
            "host_changed_or_unreachable",
        }
    },
    "exceptions": {
        "all": {
            "dhe_action_failed",
            "dhe_unavailable_action",
            "dhe_not_loaded",
            "dhe_entry_not_loaded",
            "dhe_entry_id_required",
            "dhe_invalid_config_entry",
            "dhe_weather_country_required",
            "dhe_weather_location_not_found",
            "dhe_weather_result_unavailable",
            "dhe_weather_location_id_empty",
            "dhe_unknown_weather_location_option",
            "dhe_unknown_radio_source",
            "dhe_no_radio_favorites",
            "dhe_unsupported_hvac_mode",
        }
    },
}


def _read_translation(locale: str) -> dict[str, object]:
    path = TRANSLATIONS / f"{locale}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _node(data: dict[str, object], dotted_path: str) -> dict[str, object]:
    current: object = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(part)
        current = current[part]
    if not isinstance(current, dict):
        raise TypeError(dotted_path)
    return current


def _check_locale(locale: str, data: dict[str, object]) -> list[str]:
    issues: list[str] = []
    for path, scopes in REQUIRED_KEYS.items():
        required = scopes["all"]
        try:
            keys = set(_node(data, path))
        except KeyError as exc:
            issues.append(f"{locale}: missing translation section {path} (missing {exc})")
            continue
        except TypeError:
            issues.append(f"{locale}: translation section {path} must be an object")
            continue
        missing = sorted(required - keys)
        if missing:
            issues.append(
                f"{locale}: missing translation keys in {path}: {', '.join(missing)}"
            )
    return issues


def main() -> int:
    all_issues: list[str] = []
    for locale in LOCALES:
        all_issues.extend(_check_locale(locale, _read_translation(locale)))
    if all_issues:
        for issue in all_issues:
            print(f"ERROR: {issue}", file=sys.stderr)
        return 1
    print("translation key guard ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
