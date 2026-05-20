"""Discovery cache and health helpers for DHE setup flows."""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DEFAULT_NAME, DEFAULT_PORT, DOMAIN
from .setup_scan import DHEHostCandidate

DISCOVERY_DATA_KEY = f"{DOMAIN}_discovery"
DISCOVERY_CACHE_FILE = ".storage/stiebel_dhe_connect_discovery_cache"
DISCOVERY_CACHE_VERSION = 1
DISCOVERY_CACHE_TTL_SECONDS = 24 * 60 * 60
DISCOVERY_PROMPT_SUPPRESS_SECONDS = 30 * 60
DISCOVERY_MAX_RECORDS = 32
DISCOVERY_DEBUG_ENV = "DHE_CONNECT_DISCOVERY_DEBUG"
DISCOVERY_MIN_PROMPT_CONFIDENCE = 55

_DHE_SERVICE_SUFFIX = "._ste-dhe._tcp.local"
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DiscoveryRecord:
    """One normalized discovery identity observation."""

    source: str
    key: str
    host: str
    port: int
    name: str
    confidence: int
    preferred_identity_source: str
    hostname: str = ""
    service_name: str = ""
    ip_address: str = ""
    evidence: tuple[str, ...] = ()
    identity_conflicts: tuple[str, ...] = ()
    hard_conflict: bool = False


@dataclass(frozen=True, slots=True)
class CachedDiscoveryChoice:
    """One cached discovery candidate that can be shown in setup."""

    key: str
    label: str
    host: str
    port: int
    name: str


def discovery_debug_enabled() -> bool:
    """Return whether extra discovery debug logging should be emitted."""
    return str(os.environ.get(DISCOVERY_DEBUG_ENV, "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def zeroconf_discovery_record(
    *,
    host: str,
    port: int,
    name: str,
    discovery_info: Any,
) -> DiscoveryRecord:
    """Return a scored discovery record from a Zeroconf payload."""
    hostname = _normalize_text(getattr(discovery_info, "hostname", ""))
    service_name = _normalize_text(getattr(discovery_info, "name", ""))
    ip_value = _normalize_text(getattr(discovery_info, "ip_address", ""))
    host = _normalize_text(host)
    name = _normalize_text(name) or DEFAULT_NAME

    evidence: list[str] = ["zeroconf"]
    if service_name.lower().rstrip(".").endswith(_DHE_SERVICE_SUFFIX):
        evidence.append("dhe_service_type")
    if _label_looks_like_dhe(name) or _label_looks_like_dhe(service_name):
        evidence.append("dhe_name_hint")
    if hostname.lower().endswith(".local"):
        evidence.append("local_hostname")
    if port == DEFAULT_PORT:
        evidence.append("default_port")

    conflicts = _identity_conflicts(host, hostname, service_name, ip_value)
    hard_conflict = any(
        conflict in conflicts
        for conflict in (
            "host_ip_differs_from_ip_address",
            "host_local_differs_from_hostname",
        )
    )
    confidence = _zeroconf_confidence(
        evidence,
        conflicts,
        hard_conflict=hard_conflict,
    )
    preferred_identity_source = _preferred_identity_source(host, hostname, ip_value)
    identity = _identity_value(preferred_identity_source, host, hostname, ip_value)
    return DiscoveryRecord(
        source="zeroconf",
        key=_record_key("zeroconf", identity, port),
        host=host,
        port=port,
        name=name,
        hostname=hostname,
        service_name=service_name,
        ip_address=ip_value,
        evidence=tuple(evidence),
        confidence=confidence,
        preferred_identity_source=preferred_identity_source,
        identity_conflicts=tuple(conflicts),
        hard_conflict=hard_conflict,
    )


def scan_discovery_record(candidate: DHEHostCandidate) -> DiscoveryRecord:
    """Return a scored discovery record from one setup-scan candidate."""
    evidence = tuple(candidate.evidence)
    confidence = min(
        100,
        35
        + min(45, len(evidence) * 15)
        + (10 if candidate.port == DEFAULT_PORT else 0),
    )
    return DiscoveryRecord(
        source="scan",
        key=_record_key("scan", candidate.host, candidate.port),
        host=candidate.host,
        port=candidate.port,
        name=DEFAULT_NAME,
        confidence=confidence,
        preferred_identity_source="scan_host",
        evidence=evidence,
    )


async def async_load_discovery_cache(hass: HomeAssistant) -> dict[str, Any]:
    """Load and cache discovery state in hass.data."""
    hass_data = _hass_data(hass)
    cached = hass_data.get(DISCOVERY_DATA_KEY)
    if isinstance(cached, dict):
        return cached

    path = _cache_path(hass)
    payload: dict[str, Any] = {"version": DISCOVERY_CACHE_VERSION, "records": {}}
    if path is not None:

        def _read() -> dict[str, Any]:
            try:
                with path.open("r", encoding="utf-8") as file:
                    loaded = json.load(file)
            except (FileNotFoundError, OSError, json.JSONDecodeError):
                return {"version": DISCOVERY_CACHE_VERSION, "records": {}}
            return loaded if isinstance(loaded, dict) else {}

        payload = await hass.async_add_executor_job(_read)
    payload = _normalized_payload(payload)
    hass_data[DISCOVERY_DATA_KEY] = payload
    return payload


async def async_record_discovery(
    hass: HomeAssistant,
    record: DiscoveryRecord,
    *,
    result: str = "seen",
    prompted: bool = False,
) -> dict[str, Any]:
    """Record one discovery observation and persist the temporary cache."""
    payload = await async_load_discovery_cache(hass)
    records = payload.setdefault("records", {})
    if not isinstance(records, dict):
        records = {}
        payload["records"] = records

    now = time.time()
    existing = records.get(record.key)
    if not isinstance(existing, dict):
        existing = {}

    updated = _record_cache_update(
        record,
        existing,
        now=now,
        result=result,
        prompted=prompted,
    )
    records[record.key] = updated
    _prune_payload(payload, now=now)
    await _async_save_discovery_cache(hass, payload)
    if discovery_debug_enabled():
        _LOGGER.debug(
            "DHE discovery update: source=%s confidence=%s preferred=%s "
            "conflicts=%s result=%s prompted=%s seen_count=%s",
            record.source,
            record.confidence,
            record.preferred_identity_source,
            bool(record.identity_conflicts),
            result,
            prompted,
            updated["seen_count"],
        )
    return updated


async def async_record_scan_discoveries(
    hass: HomeAssistant,
    candidates: Sequence[DHEHostCandidate],
) -> None:
    """Record setup-scan candidates for health diagnostics."""
    selected_candidates = candidates[:DISCOVERY_MAX_RECORDS]
    if not selected_candidates:
        return

    payload = await async_load_discovery_cache(hass)
    records = payload.setdefault("records", {})
    if not isinstance(records, dict):
        records = {}
        payload["records"] = records

    now = time.time()
    for candidate in selected_candidates:
        record = scan_discovery_record(candidate)
        existing = records.get(record.key)
        if not isinstance(existing, dict):
            existing = {}
        records[record.key] = _record_cache_update(
            record,
            existing,
            now=now,
            result="scan_found",
            prompted=False,
        )
    _prune_payload(payload, now=now)
    await _async_save_discovery_cache(hass, payload)


async def async_recent_discovery_prompt_seen(
    hass: HomeAssistant,
    record: DiscoveryRecord,
) -> bool:
    """Return whether an automatic discovery prompt was shown recently."""
    payload = await async_load_discovery_cache(hass)
    records = payload.get("records")
    if not isinstance(records, Mapping):
        return False
    existing = records.get(record.key)
    if not isinstance(existing, Mapping):
        return False
    if existing.get("last_result") == "created":
        return False
    if existing.get("last_result") not in {"prompted", "recently_discovered"}:
        return False
    prompted_ts = _coerce_float(existing.get("last_prompted_ts"))
    return (
        prompted_ts > 0
        and time.time() - prompted_ts < DISCOVERY_PROMPT_SUPPRESS_SECONDS
    )


def cached_discovery_choices(hass: HomeAssistant) -> list[CachedDiscoveryChoice]:
    """Return recent cached Zeroconf choices for user-started setup."""
    payload = _hass_data(hass).get(DISCOVERY_DATA_KEY)
    if not isinstance(payload, Mapping):
        return []
    records = payload.get("records")
    if not isinstance(records, Mapping):
        return []
    now = time.time()
    choices: list[CachedDiscoveryChoice] = []
    for key, record in records.items():
        if not isinstance(record, Mapping):
            continue
        if record.get("source") != "zeroconf":
            continue
        if _is_record_expired(record, now=now):
            continue
        if _coerce_int(record.get("confidence")) < DISCOVERY_MIN_PROMPT_CONFIDENCE:
            continue
        if record.get("hard_conflict"):
            continue
        host = _normalize_text(record.get("host"))
        port = _coerce_int(record.get("port"))
        if not host or port <= 0:
            continue
        name = _normalize_text(record.get("name")) or DEFAULT_NAME
        choices.append(
            CachedDiscoveryChoice(
                key=str(key),
                label=f"{name} ({host}:{port})",
                host=host,
                port=port,
                name=name,
            )
        )
    return sorted(choices, key=lambda choice: (choice.name, choice.host, choice.port))


def discovery_health_diagnostics(hass: HomeAssistant) -> dict[str, Any]:
    """Return compact discovery health data for support diagnostics."""
    payload = _hass_data(hass).get(DISCOVERY_DATA_KEY)
    if not isinstance(payload, Mapping):
        return {
            "loaded": False,
            "debug_mode": discovery_debug_enabled(),
        }
    records = payload.get("records")
    if not isinstance(records, Mapping):
        records = {}
    now = time.time()
    all_records = [record for record in records.values() if isinstance(record, Mapping)]
    recent_records = [
        record for record in all_records if not _is_record_expired(record, now=now)
    ]
    recent_records = sorted(recent_records, key=_record_last_seen_ts, reverse=True)
    zeroconf_records = [
        record for record in all_records if record.get("source") == "zeroconf"
    ]
    recent_zeroconf_records = [
        record for record in zeroconf_records if not _is_record_expired(record, now=now)
    ]
    recent_zeroconf_records = sorted(
        recent_zeroconf_records,
        key=_record_last_seen_ts,
        reverse=True,
    )
    sources = _count_by(recent_records, "source")
    preferred_sources = _count_by(recent_records, "preferred_identity_source")
    confidence = {
        "high": sum(
            1
            for record in recent_records
            if _coerce_int(record.get("confidence")) >= 80
        ),
        "medium": sum(
            1
            for record in recent_records
            if 55 <= _coerce_int(record.get("confidence")) < 80
        ),
        "low": sum(
            1 for record in recent_records if _coerce_int(record.get("confidence")) < 55
        ),
    }
    last_record = recent_records[0] if recent_records else None
    return {
        "loaded": True,
        "debug_mode": discovery_debug_enabled(),
        "cache_version": payload.get("version"),
        "record_count": len(records),
        "recent_record_count": len(recent_records),
        "cache_state": _discovery_cache_state(
            payload,
            all_records,
            recent_records,
        ),
        "zeroconf_cache": _zeroconf_cache_state(
            zeroconf_records,
            recent_zeroconf_records,
            now=now,
        ),
        "sources": sources,
        "preferred_identity_sources": preferred_sources,
        "confidence": confidence,
        "conflicting_identity_count": sum(
            1 for record in recent_records if record.get("identity_conflicts")
        ),
        "hard_conflict_count": sum(
            1 for record in recent_records if record.get("hard_conflict")
        ),
        "last_seen": last_record.get("last_seen") if last_record else None,
        "last_source": last_record.get("source") if last_record else None,
        "records": [
            _record_diagnostic_summary(record) for record in recent_records[:8]
        ],
    }


def _discovery_cache_state(
    payload: Mapping[str, Any],
    all_records: Sequence[Mapping[str, Any]],
    recent_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "version_supported": payload.get("version") == DISCOVERY_CACHE_VERSION,
        "ttl_seconds": DISCOVERY_CACHE_TTL_SECONDS,
        "prompt_suppress_seconds": DISCOVERY_PROMPT_SUPPRESS_SECONDS,
        "max_records": DISCOVERY_MAX_RECORDS,
        "stored_record_count": len(all_records),
        "recent_record_count": len(recent_records),
        "expired_record_count": max(0, len(all_records) - len(recent_records)),
    }


def _zeroconf_cache_state(
    zeroconf_records: Sequence[Mapping[str, Any]],
    recent_zeroconf_records: Sequence[Mapping[str, Any]],
    *,
    now: float,
) -> dict[str, Any]:
    last_record = recent_zeroconf_records[0] if recent_zeroconf_records else None
    oldest_record = (
        min(recent_zeroconf_records, key=_record_last_seen_ts)
        if recent_zeroconf_records
        else None
    )
    prompted_record = max(
        recent_zeroconf_records,
        key=lambda record: _coerce_float(record.get("last_prompted_ts")),
        default=None,
    )
    prompted_ts = (
        _coerce_float(prompted_record.get("last_prompted_ts"))
        if prompted_record is not None
        else 0
    )
    return {
        "record_count": len(zeroconf_records),
        "recent_record_count": len(recent_zeroconf_records),
        "expired_record_count": max(
            0,
            len(zeroconf_records) - len(recent_zeroconf_records),
        ),
        "newest_age_seconds": _record_age_seconds(last_record, now=now),
        "oldest_age_seconds": _record_age_seconds(oldest_record, now=now),
        "last_prompt_age_seconds": (
            _age_seconds(prompted_ts, now=now) if prompted_ts > 0 else None
        ),
        "prompt_suppression_active": (
            prompted_ts > 0 and now - prompted_ts < DISCOVERY_PROMPT_SUPPRESS_SECONDS
        ),
    }


def _cache_path(hass: HomeAssistant) -> Path | None:
    config = getattr(hass, "config", None)
    path = getattr(config, "path", None)
    if path is None:
        return None
    try:
        return Path(path(DISCOVERY_CACHE_FILE))
    except (TypeError, ValueError):
        return None


def _hass_data(hass: HomeAssistant) -> dict[str, Any]:
    data = getattr(hass, "data", None)
    if isinstance(data, dict):
        return data
    data = {}
    try:
        setattr(hass, "data", data)
    except (AttributeError, TypeError):
        return {}
    return data


def _record_cache_update(
    record: DiscoveryRecord,
    existing: Mapping[str, Any],
    *,
    now: float,
    result: str,
    prompted: bool,
) -> dict[str, Any]:
    prompt_count = _coerce_int(existing.get("prompt_count"))
    updated: dict[str, Any] = {
        "source": record.source,
        "host": record.host,
        "port": record.port,
        "name": record.name,
        "hostname": record.hostname,
        "service_name": record.service_name,
        "ip_address": record.ip_address,
        "confidence": record.confidence,
        "preferred_identity_source": record.preferred_identity_source,
        "evidence": list(record.evidence),
        "identity_conflicts": list(record.identity_conflicts),
        "hard_conflict": record.hard_conflict,
        "first_seen_ts": _coerce_float(existing.get("first_seen_ts"), default=now),
        "first_seen": str(existing.get("first_seen") or _format_timestamp(now)),
        "last_seen_ts": now,
        "last_seen": _format_timestamp(now),
        "seen_count": _coerce_int(existing.get("seen_count")) + 1,
        "last_result": result,
        "prompt_count": prompt_count,
    }
    if prompted:
        updated["last_prompted_ts"] = now
        updated["last_prompted"] = _format_timestamp(now)
        updated["prompt_count"] = prompt_count + 1
    elif "last_prompted_ts" in existing:
        updated["last_prompted_ts"] = existing.get("last_prompted_ts")
        updated["last_prompted"] = existing.get("last_prompted")
    return updated


async def _async_save_discovery_cache(
    hass: HomeAssistant,
    payload: Mapping[str, Any],
) -> None:
    path = _cache_path(hass)
    if path is None:
        return

    def _write() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.tmp")
        with tmp_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, sort_keys=True)
        tmp_path.replace(path)

    await hass.async_add_executor_job(_write)


def _normalized_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("version") != DISCOVERY_CACHE_VERSION:
        return {"version": DISCOVERY_CACHE_VERSION, "records": {}}
    records = payload.get("records")
    return {
        "version": DISCOVERY_CACHE_VERSION,
        "records": records if isinstance(records, dict) else {},
    }


def _prune_payload(payload: dict[str, Any], *, now: float) -> None:
    records = payload.get("records")
    if not isinstance(records, dict):
        payload["records"] = {}
        return
    for key, record in list(records.items()):
        if not isinstance(record, Mapping) or _is_record_expired(record, now=now):
            records.pop(key, None)
    if len(records) <= DISCOVERY_MAX_RECORDS:
        return
    sorted_items = sorted(records.items(), key=_record_retention_key, reverse=True)
    payload["records"] = dict(sorted_items[:DISCOVERY_MAX_RECORDS])


def _record_retention_key(item: tuple[Any, Any]) -> tuple[int, float]:
    record = item[1]
    if not isinstance(record, Mapping):
        return (0, 0)
    last_seen_ts = _record_last_seen_ts(record)
    result = str(record.get("last_result") or "")
    source = str(record.get("source") or "")
    if source == "zeroconf" and result in {"prompted", "recently_discovered"}:
        return (3, last_seen_ts)
    if source == "zeroconf":
        return (2, last_seen_ts)
    return (1, last_seen_ts)


def _record_last_seen_ts(record: Mapping[str, Any]) -> float:
    try:
        return float(record.get("last_seen_ts") or 0)
    except (TypeError, ValueError):
        return 0


def _record_age_seconds(record: Mapping[str, Any] | None, *, now: float) -> int | None:
    if record is None:
        return None
    return _age_seconds(_record_last_seen_ts(record), now=now)


def _age_seconds(timestamp: float, *, now: float) -> int | None:
    if timestamp <= 0:
        return None
    return max(0, round(now - timestamp))


def _is_record_expired(record: Mapping[str, Any], *, now: float) -> bool:
    last_seen_ts = _record_last_seen_ts(record)
    return last_seen_ts <= 0 or now - last_seen_ts > DISCOVERY_CACHE_TTL_SECONDS


def _record_key(source: str, identity: str, port: int) -> str:
    return f"{source}:{identity.lower()}:{port}"


def _identity_value(source: str, host: str, hostname: str, ip_value: str) -> str:
    if source == "hostname" and hostname:
        return hostname
    if source == "ip_address" and ip_value:
        return ip_value
    return host


def _preferred_identity_source(host: str, hostname: str, ip_value: str) -> str:
    if hostname.lower().endswith(".local"):
        return "hostname"
    if _is_ip_address(host):
        return "ip_address" if ip_value else "host"
    return "host"


def _identity_conflicts(
    host: str,
    hostname: str,
    service_name: str,
    ip_value: str,
) -> list[str]:
    conflicts: list[str] = []
    if _is_ip_address(host) and _is_ip_address(ip_value) and host != ip_value:
        conflicts.append("host_ip_differs_from_ip_address")
    if (
        host.lower().endswith(".local")
        and hostname.lower().endswith(".local")
        and host.lower().rstrip(".") != hostname.lower().rstrip(".")
    ):
        conflicts.append("host_local_differs_from_hostname")
    host_identity = hostname or host
    host_label = (
        _device_label(host_identity) if host_identity.lower().endswith(".local") else ""
    )
    service_label = _device_label(service_name)
    if host_label and service_label and not _labels_match(host_label, service_label):
        conflicts.append("service_name_differs_from_hostname")
    return conflicts


def _zeroconf_confidence(
    evidence: Sequence[str],
    conflicts: Sequence[str],
    *,
    hard_conflict: bool,
) -> int:
    confidence = 40
    if "dhe_service_type" in evidence:
        confidence += 25
    if "dhe_name_hint" in evidence:
        confidence += 10
    if "local_hostname" in evidence:
        confidence += 5
    if "default_port" in evidence:
        confidence += 10
    confidence -= 30 if hard_conflict else 0
    confidence -= 10 * len([conflict for conflict in conflicts if conflict])
    return max(0, min(100, confidence))


def _record_diagnostic_summary(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source": record.get("source"),
        "confidence": record.get("confidence"),
        "preferred_identity_source": record.get("preferred_identity_source"),
        "has_host": bool(record.get("host")),
        "has_hostname": bool(record.get("hostname")),
        "has_ip_address": bool(record.get("ip_address")),
        "uses_default_port": record.get("port") == DEFAULT_PORT,
        "evidence_count": len(record.get("evidence") or ()),
        "identity_conflicts": list(record.get("identity_conflicts") or ()),
        "first_seen": record.get("first_seen"),
        "last_seen": record.get("last_seen"),
        "seen_count": record.get("seen_count"),
        "prompt_count": record.get("prompt_count"),
        "last_result": record.get("last_result"),
    }


def _count_by(records: Sequence[Mapping[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = str(record.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().rstrip(".")


def _format_timestamp(timestamp: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp))


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coerce_float(value: Any, *, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_ip_address(value: str) -> bool:
    if not value:
        return False
    try:
        ip_address(value)
    except ValueError:
        return False
    return True


def _device_label(value: str) -> str:
    text = _normalize_text(value).lower()
    if text.endswith(_DHE_SERVICE_SUFFIX):
        text = text[: -len(_DHE_SERVICE_SUFFIX)]
    if text.endswith(".local"):
        text = text[:-6]
    for prefix in ("dhe connect ", "stiebel ", "ste "):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return "".join(ch for ch in text if ch.isalnum())


def _label_looks_like_dhe(value: str) -> bool:
    label = _device_label(value)
    return "dhe" in label or "ja06" in label


def _labels_match(left: str, right: str) -> bool:
    return left == right or left in right or right in left
