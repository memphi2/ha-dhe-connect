"""Smoke checks for a mounted Home Assistant test configuration."""

from __future__ import annotations

import argparse
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any


DOMAIN = "stiebel_dhe_connect"
DEFAULT_CONFIG = Path("/mnt/ha-test-config")
LOCALHOST_CLIENT_ID = "http://localhost/"
BAD_STATES = {"unavailable", "unknown"}
LOG_ERROR_MARKERS = ("ERROR", "CRITICAL", "Traceback", "Exception")
LOG_WARNING_MARKERS = ("WARNING",)


@dataclass(frozen=True)
class EntityRegistryEntry:
    """Enabled DHE entity entry from Home Assistant's entity registry."""

    entity_id: str
    domain: str
    platform: str
    disabled_by: str | None = None


@dataclass(frozen=True)
class LatestState:
    """Latest recorder state for a Home Assistant entity."""

    entity_id: str
    state: str
    attributes: dict[str, Any]
    state_id: int
    last_updated: float | str | None


@dataclass(frozen=True)
class CheckResult:
    """One smoke-check result line."""

    ok: bool
    message: str


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _storage_path(config: Path, filename: str) -> Path:
    return config / ".storage" / filename


def load_entity_registry(config: Path) -> list[EntityRegistryEntry]:
    """Return enabled DHE entities from Home Assistant's entity registry."""
    path = _storage_path(config, "core.entity_registry")
    if not path.exists():
        return []

    data = _load_json(path)
    raw_entities = data.get("data", {}).get("entities", [])
    entries: list[EntityRegistryEntry] = []
    for raw in raw_entities:
        if not isinstance(raw, dict):
            continue
        platform = str(raw.get("platform") or "")
        entity_id = str(raw.get("entity_id") or "")
        if platform != DOMAIN or "." not in entity_id:
            continue
        domain = entity_id.split(".", 1)[0]
        disabled_by = raw.get("disabled_by")
        if disabled_by is not None:
            disabled_by = str(disabled_by)
        entries.append(
            EntityRegistryEntry(
                entity_id=entity_id,
                domain=domain,
                platform=platform,
                disabled_by=disabled_by,
            )
        )
    return sorted(entries, key=lambda item: item.entity_id)


def enabled_entity_ids(entries: Iterable[EntityRegistryEntry]) -> list[str]:
    """Return enabled entity IDs from registry entries."""
    return [entry.entity_id for entry in entries if entry.disabled_by is None]


def count_localhost_refresh_tokens(config: Path) -> int:
    """Count temporary localhost refresh tokens in Home Assistant auth storage."""
    path = _storage_path(config, "auth")
    if not path.exists():
        return 0

    data = _load_json(path)
    tokens = data.get("data", {}).get("refresh_tokens", [])
    if isinstance(tokens, dict):
        values = tokens.values()
    elif isinstance(tokens, list):
        values = tokens
    else:
        values = []
    return sum(
        1
        for token in values
        if isinstance(token, dict) and token.get("client_id") == LOCALHOST_CLIENT_ID
    )


def check_localhost_refresh_tokens(
    config: Path,
    *,
    allow_tokens: bool = False,
) -> CheckResult:
    """Return a structured result for temporary localhost auth tokens."""
    try:
        localhost_tokens = count_localhost_refresh_tokens(config)
    except json.JSONDecodeError as err:
        return CheckResult(False, f"auth storage contains invalid JSON: {err}")
    except OSError as err:
        return CheckResult(False, f"auth storage cannot be read: {err}")

    return CheckResult(
        allow_tokens or localhost_tokens == 0,
        f"localhost HA refresh tokens={localhost_tokens}",
    )


def _connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _state_timestamp_expression(conn: sqlite3.Connection) -> str:
    columns = _table_columns(conn, "states")
    if "last_updated_ts" in columns:
        return "s.last_updated_ts"
    if "last_updated" in columns:
        return "s.last_updated"
    return "NULL"


def _state_attributes_expression(conn: sqlite3.Connection) -> str:
    columns = _table_columns(conn, "state_attributes")
    if "shared_attrs" in columns:
        return "sa.shared_attrs"
    if "attributes" in columns:
        return "sa.attributes"
    return "NULL"


def _fallback_entity_ids(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT entity_id
        FROM states_meta
        WHERE entity_id LIKE ?
        ORDER BY entity_id
        """,
        ("%dhe%connect%",),
    )
    return [str(row["entity_id"]) for row in rows]


def load_latest_states(db_path: Path, entity_ids: Iterable[str]) -> dict[str, LatestState]:
    """Load the newest recorder state for each requested entity."""
    entity_id_list = sorted(set(entity_ids))
    with _connect_db(db_path) as conn:
        if not entity_id_list:
            entity_id_list = _fallback_entity_ids(conn)
        if not entity_id_list:
            return {}

        placeholders = ",".join("?" for _ in entity_id_list)
        timestamp_expression = _state_timestamp_expression(conn)
        attributes_expression = _state_attributes_expression(conn)
        query = f"""
            WITH metadata AS (
                SELECT metadata_id, entity_id
                FROM states_meta
                WHERE entity_id IN ({placeholders})
            ),
            latest AS (
                SELECT metadata_id, max(state_id) AS state_id
                FROM states
                WHERE metadata_id IN (SELECT metadata_id FROM metadata)
                GROUP BY metadata_id
            )
            SELECT
                m.entity_id,
                s.state,
                s.state_id,
                {timestamp_expression} AS last_updated,
                {attributes_expression} AS shared_attrs
            FROM latest l
            JOIN states s ON s.state_id = l.state_id
            JOIN metadata m ON m.metadata_id = s.metadata_id
            LEFT JOIN state_attributes sa ON sa.attributes_id = s.attributes_id
            ORDER BY m.entity_id
        """
        rows = conn.execute(query, entity_id_list).fetchall()

    states: dict[str, LatestState] = {}
    for row in rows:
        attributes: dict[str, Any] = {}
        raw_attrs = row["shared_attrs"]
        if isinstance(raw_attrs, str) and raw_attrs:
            try:
                parsed = json.loads(raw_attrs)
            except json.JSONDecodeError:
                parsed = {}
            if isinstance(parsed, dict):
                attributes = parsed
        states[str(row["entity_id"])] = LatestState(
            entity_id=str(row["entity_id"]),
            state=str(row["state"]),
            attributes=attributes,
            state_id=int(row["state_id"]),
            last_updated=row["last_updated"],
        )
    return states


def count_recorder_writes(
    db_path: Path,
    entity_ids: Iterable[str],
    *,
    after_state_id: int,
) -> dict[str, int]:
    """Count recorder writes for requested entities after a state_id marker."""
    entity_id_list = sorted(set(entity_ids))
    with _connect_db(db_path) as conn:
        if not entity_id_list:
            entity_id_list = _fallback_entity_ids(conn)
        if not entity_id_list:
            return {}

        placeholders = ",".join("?" for _ in entity_id_list)
        rows = conn.execute(
            f"""
            SELECT sm.entity_id, count(*) AS writes
            FROM states s
            JOIN states_meta sm ON sm.metadata_id = s.metadata_id
            WHERE s.state_id > ?
              AND sm.entity_id IN ({placeholders})
            GROUP BY sm.entity_id
            ORDER BY writes DESC, sm.entity_id
            """,
            [after_state_id, *entity_id_list],
        ).fetchall()
    return {str(row["entity_id"]): int(row["writes"]) for row in rows}


def max_state_id(db_path: Path) -> int:
    """Return the newest recorder state_id."""
    with _connect_db(db_path) as conn:
        value = conn.execute("SELECT max(state_id) FROM states").fetchone()[0]
    return int(value or 0)


def _is_connection_sensor_entity_id(entity_id: str) -> bool:
    return entity_id.startswith("sensor.") and (
        "verbindungsstatus" in entity_id or "connection_state" in entity_id
    )


def _is_reconnect_count_entity_id(entity_id: str) -> bool:
    return entity_id.startswith("sensor.") and (
        "reconnect_count" in entity_id
        or "reconnects" in entity_id
        or "wiederverbindungen" in entity_id
    )


def evaluate_state_health(
    entries: Iterable[EntityRegistryEntry],
    states: dict[str, LatestState],
) -> list[CheckResult]:
    """Evaluate current DHE states for common HA-test regressions."""
    enabled_entries = [entry for entry in entries if entry.disabled_by is None]
    enabled_ids = [entry.entity_id for entry in enabled_entries]
    results: list[CheckResult] = []

    if enabled_ids:
        missing = sorted(set(enabled_ids) - set(states))
        results.append(
            CheckResult(
                not missing,
                (
                    f"all {len(enabled_ids)} enabled DHE registry entities have "
                    "recorder states"
                    if not missing
                    else f"missing recorder states: {', '.join(missing[:8])}"
                ),
            )
        )
    else:
        results.append(
            CheckResult(
                bool(states),
                (
                    f"found {len(states)} DHE recorder entities without registry data"
                    if states
                    else "no DHE entities found in registry or recorder"
                ),
            )
        )

    climate_states = [
        state
        for state in states.values()
        if state.entity_id.startswith("climate.")
    ]
    results.append(
        CheckResult(
            bool(climate_states),
            (
                "climate entity present"
                if climate_states
                else "no DHE climate entity state found"
            ),
        )
    )
    for state in climate_states:
        ok = state.state not in BAD_STATES
        details = [f"{state.entity_id}={state.state!r}"]
        connection_state = state.attributes.get("connection_state")
        if connection_state is not None:
            details.append(f"connection_state={connection_state!r}")
            ok = ok and connection_state == "connected"
        results.append(CheckResult(ok, " ".join(details)))

    enabled_connection_ids = {
        entry.entity_id
        for entry in enabled_entries
        if _is_connection_sensor_entity_id(entry.entity_id)
    }
    connection_candidates = [
        state
        for state in states.values()
        if _is_connection_sensor_entity_id(state.entity_id)
        and (not enabled_entries or state.entity_id in enabled_connection_ids)
    ]
    if connection_candidates:
        for state in connection_candidates:
            results.append(
                CheckResult(
                    state.state == "connected",
                    f"{state.entity_id}={state.state!r}",
                )
            )
    else:
        results.append(
            CheckResult(
                bool(enabled_entries),
                (
                    "connection-state sensor disabled or not present; skipped"
                    if enabled_entries
                    else "connection-state sensor not found in recorder"
                ),
            )
        )

    reconnect_candidates = [
        state
        for state in states.values()
        if _is_reconnect_count_entity_id(state.entity_id)
    ]
    if reconnect_candidates:
        for state in reconnect_candidates:
            results.append(
                CheckResult(
                    state.state in {"0", "0.0"},
                    f"{state.entity_id}={state.state!r}",
                )
            )

    for state in sorted(states.values(), key=lambda item: item.entity_id):
        if state.entity_id.startswith("button."):
            continue
        if state.state in BAD_STATES:
            results.append(
                CheckResult(False, f"{state.entity_id} has bad state {state.state!r}")
            )

    return results


def scan_logs(
    config: Path,
    *,
    fail_on_warning: bool = False,
    include_fault_log: bool = False,
) -> list[CheckResult]:
    """Scan current HA logs for DHE-related errors."""
    log_paths = [
        config / "home-assistant.log",
        config / "home-assistant.log.1",
    ]
    if include_fault_log:
        log_paths.append(config / "home-assistant.log.fault")

    markers = LOG_ERROR_MARKERS + (LOG_WARNING_MARKERS if fail_on_warning else ())
    hits: list[str] = []
    inspected_paths = 0
    for path in log_paths:
        if not path.exists():
            continue
        inspected_paths += 1
        recent_error_line: str | None = None
        recent_error_remaining = 0
        for line in _tail_log_lines(path, 20_000):
            mentions_dhe = _line_mentions_dhe(line)
            has_marker = _line_has_log_marker(line, markers)
            if mentions_dhe and has_marker:
                hits.append(f"{path.name}: {line[:240]}")
            elif (
                mentions_dhe
                and recent_error_line is not None
                and (
                    _line_mentions_dhe(recent_error_line)
                    or _line_is_traceback_frame(line)
                )
            ):
                hits.append(
                    f"{path.name}: {recent_error_line[:160]} ... {line[:160]}"
                )

            if has_marker:
                recent_error_line = line
                recent_error_remaining = 25
            elif recent_error_remaining > 0:
                recent_error_remaining -= 1
                if recent_error_remaining == 0:
                    recent_error_line = None

    if hits:
        return [CheckResult(False, hit) for hit in hits[:10]]
    if inspected_paths == 0:
        return [
            CheckResult(
                False,
                "no Home Assistant log files found for DHE log scan",
            )
        ]
    return [CheckResult(True, "no DHE-related errors in current HA logs")]


def _line_mentions_dhe(line: str) -> bool:
    lower = line.lower()
    return DOMAIN in lower or "dhe" in lower or "stiebel" in lower


def _line_has_log_marker(line: str, markers: tuple[str, ...]) -> bool:
    return any(marker in line for marker in markers)


def _line_is_traceback_frame(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith('File "') or "/custom_components/" in stripped


def _tail_log_lines(path: Path, line_limit: int) -> list[str]:
    with path.open("r", encoding="utf-8", errors="replace") as file:
        return [line.rstrip("\n") for line in deque(file, maxlen=line_limit)]


def evaluate_recorder_writes(
    writes: dict[str, int],
    *,
    max_total_writes: int,
    max_entity_writes: int,
) -> list[CheckResult]:
    """Evaluate recorder write volume during a monitor interval."""
    total = sum(writes.values())
    results = [
        CheckResult(
            total <= max_total_writes,
            f"recorder writes total={total} limit={max_total_writes}",
        )
    ]
    for entity_id, count in sorted(
        writes.items(),
        key=lambda item: (-item[1], item[0]),
    ):
        results.append(
            CheckResult(
                count <= max_entity_writes,
                f"recorder writes {entity_id}={count} limit={max_entity_writes}",
            )
        )
    return results


def _print_result(result: CheckResult) -> None:
    prefix = "PASS" if result.ok else "FAIL"
    print(f"{prefix}: {result.message}")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke-test a mounted Home Assistant test configuration.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"Home Assistant config path, defaults to {DEFAULT_CONFIG}",
    )
    parser.add_argument(
        "--db",
        type=Path,
        help="Recorder database path, defaults to <config>/home-assistant_v2.db",
    )
    parser.add_argument(
        "--monitor-seconds",
        type=int,
        default=0,
        help="Watch recorder writes for this many seconds after state checks.",
    )
    parser.add_argument(
        "--max-total-writes",
        type=int,
        default=10,
        help="Maximum DHE recorder writes allowed during monitoring.",
    )
    parser.add_argument(
        "--max-entity-writes",
        type=int,
        default=5,
        help="Maximum writes allowed for one DHE entity during monitoring.",
    )
    parser.add_argument(
        "--allow-localhost-tokens",
        action="store_true",
        help="Do not fail when temporary localhost HA refresh tokens exist.",
    )
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Treat DHE-related HA WARNING log lines as smoke failures.",
    )
    parser.add_argument(
        "--include-fault-log",
        action="store_true",
        help="Also scan home-assistant.log.fault.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    config = args.config
    db_path = args.db or config / "home-assistant_v2.db"
    results: list[CheckResult] = []

    results.append(CheckResult(config.exists(), f"config path exists: {config}"))
    results.append(CheckResult(db_path.exists(), f"recorder DB exists: {db_path}"))
    if not config.exists() or not db_path.exists():
        for result in results:
            _print_result(result)
        return 1

    try:
        entries = load_entity_registry(config)
    except json.JSONDecodeError as err:
        entries = []
        results.append(CheckResult(False, f"entity registry contains invalid JSON: {err}"))
    except OSError as err:
        entries = []
        results.append(CheckResult(False, f"entity registry cannot be read: {err}"))
    enabled_ids = enabled_entity_ids(entries)
    results.append(
        CheckResult(
            True,
            (
                f"loaded {len(enabled_ids)} enabled DHE entities from registry"
                if entries
                else "DHE registry entries not found; using recorder fallback"
            ),
        )
    )

    results.append(
        check_localhost_refresh_tokens(
            config,
            allow_tokens=args.allow_localhost_tokens,
        )
    )

    try:
        latest_states = load_latest_states(db_path, enabled_ids)
    except sqlite3.Error as err:
        latest_states = {}
        results.append(CheckResult(False, f"recorder query failed: {err}"))
    else:
        results.extend(evaluate_state_health(entries, latest_states))

    results.extend(
        scan_logs(
            config,
            fail_on_warning=args.fail_on_warning,
            include_fault_log=args.include_fault_log,
        )
    )

    if args.monitor_seconds > 0 and latest_states:
        start_state_id = max_state_id(db_path)
        print(
            f"INFO: monitoring recorder writes for {args.monitor_seconds}s "
            f"from state_id {start_state_id}"
        )
        time.sleep(args.monitor_seconds)
        writes = count_recorder_writes(
            db_path,
            latest_states,
            after_state_id=start_state_id,
        )
        results.extend(
            evaluate_recorder_writes(
                writes,
                max_total_writes=args.max_total_writes,
                max_entity_writes=args.max_entity_writes,
            )
        )

    for result in results:
        _print_result(result)
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
