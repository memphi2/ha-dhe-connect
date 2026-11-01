"""Regression checks for the soak gate itself, including injected growth."""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.check_runtime_soak import LIMITS, main, sample_errors


class RuntimeSoakCheckTests(unittest.TestCase):
    def _samples(self):
        return [
            {"phase": phase, **dict.fromkeys(LIMITS, 0), "retained_clients": 0}
            for phase in ("connected", "reconnected", "idle", "unloaded")
            for _ in range(2)
        ]

    def test_stable_samples_pass(self):
        self.assertEqual(sample_errors(self._samples()), [])

    def test_each_growth_limit_is_enforced(self):
        for metric, limit in LIMITS.items():
            with self.subTest(metric=metric):
                samples = self._samples()
                samples[1][metric] = limit + 1
                self.assertTrue(sample_errors(samples))

    def test_constant_leftovers_are_rejected(self):
        for metric in ("owned_tasks", "callbacks", "retained_clients"):
            with self.subTest(metric=metric):
                samples = self._samples()
                for sample in samples:
                    if sample["phase"] == "unloaded":
                        sample[metric] = 1
                self.assertTrue(sample_errors(samples))

    def test_missing_samples_fail(self):
        self.assertTrue(sample_errors([]))

    def test_optional_rss_and_invalid_metrics(self):
        samples = self._samples()
        for sample in samples:
            sample["rss_bytes"] = None
        self.assertEqual(sample_errors(samples), [])
        samples[0]["tasks"] = None
        self.assertTrue(sample_errors(samples))

    def test_finishing_transient_tasks_are_not_growth(self):
        samples = self._samples()
        samples[0]["owned_tasks"] = 4
        samples[1]["owned_tasks"] = 2
        self.assertEqual(sample_errors(samples), [])

    def test_cli_rejects_invalid_limits(self):
        for args in (
            ["--cycles", "2"],
            ["--idle-seconds", "nan"],
            ["--idle-seconds", "inf"],
            ["--idle-seconds", "0"],
        ):
            with self.subTest(args=args), redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as error:
                    main(args)
                self.assertEqual(error.exception.code, 2)

    def test_cli_uses_isolated_process_and_fresh_report(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            report.write_text("stale report", encoding="utf-8")

            def run(command, *, cwd, env, check):
                self.assertFalse(report.exists())
                self.assertIn("tests/test_01_runtime_soak.py", command)
                self.assertFalse(check)
                self.assertTrue((cwd / "pyproject.toml").exists())
                self.assertEqual(env["DHE_SOAK_CYCLES"], "3")
                self.assertEqual(env["DHE_SOAK_REPORT"], str(report))
                report.write_text(
                    json.dumps(
                        {"cycles": 3, "idle_seconds": 0.5, "errors": [], "samples": []}
                    ),
                    encoding="utf-8",
                )
                return SimpleNamespace(returncode=0)

            with (
                patch("scripts.check_runtime_soak.subprocess.run", side_effect=run),
                redirect_stdout(StringIO()),
            ):
                self.assertEqual(
                    main(
                        [
                            "--cycles",
                            "3",
                            "--idle-seconds",
                            "0.5",
                            "--json-output",
                            str(report),
                        ]
                    ),
                    0,
                )

    def test_cli_fails_without_report_and_preserves_child_failure(self):
        for code in (0, 7):
            with (
                self.subTest(code=code),
                patch(
                    "scripts.check_runtime_soak.subprocess.run",
                    return_value=SimpleNamespace(returncode=code),
                ),
                redirect_stderr(StringIO()),
            ):
                self.assertEqual(
                    main(["--cycles", "3", "--idle-seconds", "0.5"]), code or 1
                )
