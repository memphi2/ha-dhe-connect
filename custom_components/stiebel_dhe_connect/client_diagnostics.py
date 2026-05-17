"""Diagnostic and payload summary helpers for the DHE client."""

from __future__ import annotations

import re
import time
from typing import Any

BEARER_TOKEN_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
SECRET_FIELD_RE = re.compile(
    r"(?i)\b(access_token|refresh_token|password|code)"
    r"([\"']?\s*[:=]\s*[\"']?)"
    r"([^\"'\s,&)}\]]+)"
)
AUTHORIZATION_FIELD_RE = re.compile(
    r"(?i)\b(authorization)"
    r"([\"']?\s*[:=]\s*[\"']?)"
    r"(?!Bearer\b)"
    r"([^\"'\s,&)}\]]+)"
)
TOKEN_FIELD_RE = re.compile(
    r"(?i)\b(token)"
    r"([\"']?\s*[:=]\s*[\"']?)"
    r"([^\"'\s,&)}\]]+)"
)
TOKEN_QUERY_RE = re.compile(
    r"(?i)([?&](?:access_token|refresh_token|token|code)=)[^&\s]+"
)
URL_CREDENTIAL_RE = re.compile(r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@")
PRIVATE_HOST_RE = re.compile(
    r"(?<![0-9])(?:"
    r"10(?:\.[0-9]{1,3}){3}|"
    r"172\.(?:1[6-9]|2[0-9]|3[0-1])(?:\.[0-9]{1,3}){2}|"
    r"192\.168(?:\.[0-9]{1,3}){2}"
    r")(?::[0-9]+)?(?![0-9])"
)


def redact_diagnostic_text(value: object) -> str:
    """Return diagnostic text without auth material or private host details."""
    text = str(value)
    text = BEARER_TOKEN_RE.sub("Bearer <redacted>", text)
    text = URL_CREDENTIAL_RE.sub(r"\1<redacted>@", text)
    text = TOKEN_QUERY_RE.sub(r"\1<redacted>", text)
    text = SECRET_FIELD_RE.sub(r"\1\2<redacted>", text)
    text = AUTHORIZATION_FIELD_RE.sub(r"\1\2<redacted>", text)
    text = TOKEN_FIELD_RE.sub(r"\1\2<redacted>", text)
    return PRIVATE_HOST_RE.sub("<private-host>", text)


def _redacted_leaf(value: Any) -> Any:
    """Return strings redacted for diagnostics while preserving other values."""
    if isinstance(value, str):
        return redact_diagnostic_text(value)
    return value


def _unique_redacted_key(key: Any, counts: dict[str, int]) -> str:
    """Return a redacted key without dropping later colliding keys."""
    redacted = redact_diagnostic_text(key)
    count = counts.get(redacted, 0) + 1
    counts[redacted] = count
    if count == 1:
        return redacted
    return f"{redacted}#{count}"


def summarize_radio_value(value: Any) -> Any:
    """Return a compact, recorder-friendly summary for radio app payloads."""
    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            return {
                "count": len(value),
                "stations": [
                    {
                        "Id": _redacted_leaf(item.get("Id")),
                        "Name": _redacted_leaf(item.get("Name")),
                        "City": _redacted_leaf(item.get("City")),
                    }
                    for item in value[:10]
                ],
            }
        return {
            "count": len(value),
            "sample": [
                summarize_radio_value(item)
                for item in value[:10]
            ],
        }
    if isinstance(value, dict):
        if "station" in value or "favorites" in value:
            return {
                key: summarize_radio_value(item)
                for key, item in value.items()
            }
        if "Id" in value or "Name" in value or "StreamUrls" in value:
            return {
                "Id": value.get("Id"),
                "Name": _redacted_leaf(value.get("Name")),
                "City": _redacted_leaf(value.get("City")),
                "Country": _redacted_leaf(value.get("Country")),
                "Genres": summarize_radio_value(value.get("Genres")),
                "Logo44Url": _redacted_leaf(value.get("Logo44Url")),
            }
        return {
            key: summarize_radio_value(item)
            for key, item in value.items()
        }
    if isinstance(value, str):
        return redact_diagnostic_text(value)
    return value


def summarize_weather_location(value: dict[str, Any]) -> dict[str, Any]:
    """Return identifying fields for one weather location payload."""
    return {
        key: _redacted_leaf(value.get(key))
        for key in ("Name", "Country", "CountryId", "LocationId", "SearchType")
        if value.get(key) not in (None, "")
    }


def summarize_weather_value(value: Any) -> Any:
    """Return a compact summary for weather app payloads."""
    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            return {
                "count": len(value),
                "items": [
                    summarize_weather_location(item)
                    for item in value[:10]
                ],
            }
        return {
            "count": len(value),
            "sample": [
                summarize_weather_value(item)
                for item in value[:10]
            ],
        }
    if isinstance(value, dict):
        if "Location" in value or "CompleteDays" in value or "SimpleDays" in value:
            summary: dict[str, Any] = {}
            location = value.get("Location")
            if isinstance(location, dict):
                summary["location"] = summarize_weather_location(location)
            for key in ("CompleteDays", "SimpleDays"):
                days = value.get(key)
                if isinstance(days, list):
                    summary[key[:1].lower() + key[1:]] = {
                        "count": len(days),
                        "dates": [
                            day.get("date")
                            for day in days[:10]
                            if isinstance(day, dict) and day.get("date")
                        ],
                    }
            return summary
        if "Country" in value or "LocationId" in value:
            return summarize_weather_location(value)
        return {
            key: summarize_weather_value(item)
            for key, item in value.items()
        }
    if isinstance(value, str):
        return redact_diagnostic_text(value)
    return value


def diagnostic_error(error: BaseException) -> str:
    """Return a compact exception string for diagnostics."""
    message = redact_diagnostic_text(error)
    reason = type(error).__name__ if not message else f"{type(error).__name__}: {message}"
    return reason[:240]


def diagnostic_timestamp() -> str:
    """Return the UTC timestamp format used by diagnostic state."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def summarize_diagnostic_value(value: Any, *, depth: int = 0) -> Any:
    """Return a bounded representation of arbitrary diagnostic payload data."""
    if depth >= 3:
        return type(value).__name__
    if isinstance(value, dict):
        keys = list(value)[:8]
        key_counts: dict[str, int] = {}
        summary = {
            _unique_redacted_key(key, key_counts): summarize_diagnostic_value(
                value[key],
                depth=depth + 1,
            )
            for key in keys
        }
        if len(value) > len(keys):
            summary["_omitted_keys"] = len(value) - len(keys)
        return summary
    if isinstance(value, list):
        return {
            "type": "list",
            "count": len(value),
            "sample": [
                summarize_diagnostic_value(item, depth=depth + 1)
                for item in value[:3]
            ],
        }
    if isinstance(value, str):
        text = redact_diagnostic_text(value)
        if len(text) > 120:
            return f"{text[:117]}..."
        return text
    return value
