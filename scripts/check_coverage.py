"""Run the Silver coverage gate for deterministic integration modules.

The repository also has HA fixture, Fake-DHE and live smoke gates for platform
setup, device I/O and Home Assistant callback glue. This coverage gate keeps
the 95% threshold on deterministic parser, mapping, diagnostics and state
helper modules where line coverage is a stable signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
COVERAGE_TARGET = "custom_components/stiebel_dhe_connect"
COVERAGE_FAIL_UNDER = 95


@dataclass(frozen=True)
class CoverageExclusion:
    """One file excluded from the strict Silver line-coverage gate."""

    path: str
    reason: str


EXCLUDED_COVERAGE_FILES: tuple[CoverageExclusion, ...] = (
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/__init__.py",
        "Home Assistant setup, service registration and config-entry glue.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/binary_sensor.py",
        "Home Assistant platform entity glue.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/button.py",
        "Home Assistant platform entity glue.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/climate.py",
        "Home Assistant platform entity glue.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/media_player.py",
        "Home Assistant platform entity glue.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/number.py",
        "Home Assistant platform entity glue.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/select.py",
        "Home Assistant platform entity glue.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/sensor.py",
        "Home Assistant platform entity glue.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/switch.py",
        "Home Assistant platform entity glue.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/text.py",
        "Home Assistant platform entity glue.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/client.py",
        "Long-running client lifecycle glue covered by Fake-DHE and HA fixtures.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/client_callbacks.py",
        "Callback registration glue covered through platform fixture tests.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/client_command_runner.py",
        "Command transport orchestration covered by Fake-DHE flow tests.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/client_commands.py",
        "DHE command wrappers covered by Fake-DHE and live smoke gates.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/client_connection_state.py",
        "Reconnect availability glue covered by focused supervisor tests.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/client_device_info_commands.py",
        "DHE command wrappers covered by Fake-DHE and diagnostics tests.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/client_pairing.py",
        "Pairing protocol orchestration covered by Fake-DHE setup tests.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/client_radio_commands.py",
        "DHE radio command wrappers covered by Fake-DHE and smoke tests.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/client_runtime.py",
        "Runtime parser dispatcher with firmware-dependent edge branches.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/client_runtime_app.py",
        "Runtime app payload dispatcher with firmware-dependent edge branches.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/client_runtime_media.py",
        "Runtime radio/weather dispatcher with firmware-dependent edge branches.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/client_temperature_memory_commands.py",
        "DHE temperature-memory command wrappers covered by Fake-DHE tests.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/client_transport.py",
        "Engine.IO transport glue covered by Fake-DHE and live smoke gates.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/client_transport_auth.py",
        "Engine.IO authentication and pairing transport glue.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/client_transport_helpers.py",
        "Engine.IO transport helper edge handling covered by transport tests.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/client_weather_commands.py",
        "DHE weather command wrappers covered by Fake-DHE and service tests.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/client_web_version.py",
        "DHE web-interface version fetch glue covered by live/Fake-DHE paths.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/client_wellness_timer_commands.py",
        "DHE wellness/timer command wrappers covered by Fake-DHE tests.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/config_flow.py",
        "Home Assistant config-flow orchestration glue covered by HA fixtures.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/config_flow_discovery.py",
        "Home Assistant discovery-flow glue covered by HA fixtures.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/config_flow_mapping.py",
        "Options-flow selector glue covered by flow helper tests.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/config_flow_options.py",
        "Home Assistant options-flow orchestration glue covered by HA fixtures.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/config_flow_schemas.py",
        "Home Assistant voluptuous schema glue covered by flow tests.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/config_flow_setup.py",
        "Home Assistant setup-form glue covered by HA fixtures.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/discovery_state.py",
        "Discovery cache persistence glue covered by dedicated discovery tests.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/engineio_helpers.py",
        "Engine.IO parser edge glue covered by transport tests.",
    ),
    CoverageExclusion(
        "custom_components/stiebel_dhe_connect/setup_scan.py",
        "User-triggered network scan I/O glue covered by helper and HA tests.",
    ),
)


def _run(args: Sequence[str]) -> int:
    completed = subprocess.run(
        list(args),
        cwd=ROOT,
        check=False,
    )
    return completed.returncode


def _coverage_omit_argument() -> str:
    return ",".join(exclusion.path for exclusion in EXCLUDED_COVERAGE_FILES)


def main() -> int:
    try:
        import pytest_cov  # noqa: F401
    except ModuleNotFoundError:
        print(
            "pytest-cov is required for the Silver coverage gate. "
            "Install the repository test dependencies, then rerun.",
            file=sys.stderr,
        )
        return 2

    pytest_result = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            f"--cov={COVERAGE_TARGET}",
            "--cov-report=",
        ]
    )
    if pytest_result != 0:
        return pytest_result

    return _run(
        [
            sys.executable,
            "-m",
            "coverage",
            "report",
            f"--fail-under={COVERAGE_FAIL_UNDER}",
            "--skip-covered",
            "--show-missing",
            f"--omit={_coverage_omit_argument()}",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
