"""Diagnostic and payload summary helpers for the DHE client."""

from __future__ import annotations

import time
from typing import Any


def summarize_radio_value(value: Any) -> Any:
    """Return a compact, recorder-friendly summary for radio app payloads."""
    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            return {
                "count": len(value),
                "stations": [
                    {
                        "Id": item.get("Id"),
                        "Name": item.get("Name"),
                        "City": item.get("City"),
                    }
                    for item in value[:10]
                ],
            }
        return {
            "count": len(value),
            "sample": value[:10],
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
                "Name": value.get("Name"),
                "City": value.get("City"),
                "Country": value.get("Country"),
                "Genres": value.get("Genres"),
                "Logo44Url": value.get("Logo44Url"),
            }
        return {
            key: summarize_radio_value(item)
            for key, item in value.items()
        }
    return value


def summarize_weather_location(value: dict[str, Any]) -> dict[str, Any]:
    """Return identifying fields for one weather location payload."""
    return {
        key: value.get(key)
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
            "sample": value[:10],
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
    return value


def diagnostic_error(error: BaseException) -> str:
    """Return a compact exception string for diagnostics."""
    message = str(error)
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
        summary = {
            str(key): summarize_diagnostic_value(value[key], depth=depth + 1)
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
    if isinstance(value, str) and len(value) > 120:
        return f"{value[:117]}..."
    return value
