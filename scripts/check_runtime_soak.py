"""Run an isolated, loopback-only HA lifecycle and idle soak test."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIB = 1024 * 1024
PHASES = ("connected", "reconnected", "same_client_reconnected", "idle", "unloaded")
LIMITS = {
    "tasks": 2,
    "owned_tasks": 0,
    "scheduled_handles": 2,
    "callbacks": 0,
    "integration_bytes": MIB // 2,
    "traced_bytes": 8 * MIB,
    "rss_bytes": 32 * MIB,
}


def sample_errors(samples: list[dict[str, int | str | None]]) -> list[str]:
    """Compare like-for-like phases after warmup, without tolerating leftovers."""
    errors = []
    for phase in PHASES:
        group = [sample for sample in samples if sample["phase"] == phase]
        if len(group) < 2:
            errors.append(f"{phase}: fewer than two samples")
            continue
        for metric, limit in LIMITS.items():
            values = [sample[metric] for sample in group]
            if all(value is None for value in values) and metric == "rss_bytes":
                continue
            if any(not isinstance(value, int) for value in values):
                errors.append(f"{phase}: invalid {metric} samples")
                continue
            if max(values) - values[0] > limit:
                errors.append(f"{phase}: {metric} growth exceeds {limit}")
        if phase == "unloaded" and any(
            sample[metric] != 0
            for sample in group
            for metric in ("owned_tasks", "callbacks", "retained_clients")
        ):
            errors.append("unloaded: surviving DHE tasks, callbacks or clients")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=30)
    parser.add_argument("--idle-seconds", type=float, default=60)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args(argv)
    if (
        args.cycles < 3
        or not math.isfinite(args.idle_seconds)
        or args.idle_seconds < 0.5
    ):
        parser.error("use at least 3 cycles and 0.5 finite idle seconds")
    with tempfile.TemporaryDirectory(prefix="dhe-soak-") as directory:
        report = (args.json_output or Path(directory) / "report.json").resolve()
        report.unlink(missing_ok=True)
        env = dict(os.environ)
        env.update(
            DHE_SOAK_CYCLES=str(args.cycles),
            DHE_SOAK_IDLE_SECONDS=str(args.idle_seconds),
            DHE_SOAK_REPORT=str(report),
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--tb=short",
                "tests/test_01_runtime_soak.py",
            ],
            cwd=ROOT,
            env=env,
            check=False,
        )
        if report.exists():
            data = json.loads(report.read_text(encoding="utf-8"))
            print(
                json.dumps(
                    {key: value for key, value in data.items() if key != "samples"},
                    indent=2,
                )
            )
            if result.returncode == 0 and (
                data.get("errors")
                or data.get("cycles") != args.cycles
                or data.get("same_client_reconnects") != args.cycles + 2
                or data.get("idle_seconds") != args.idle_seconds
                or sample_errors(data.get("samples", []))
            ):
                print(
                    "FAIL: soak report does not match the requested run",
                    file=sys.stderr,
                )
                return 1
        elif result.returncode == 0:
            print("FAIL: soak test produced no report", file=sys.stderr)
            return 1
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
