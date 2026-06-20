"""Tests for setup discovery cache and health helpers."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMPONENT_DIR = ROOT / "custom_components" / "stiebel_dhe_connect"
PACKAGE_NAME = "custom_components.stiebel_dhe_connect"


def _load_component_module(module_name: str):
    try:
        from tests.test_ha_stubs import ensure_homeassistant_stubs
    except ModuleNotFoundError:
        from test_ha_stubs import ensure_homeassistant_stubs

    ensure_homeassistant_stubs()
    root_module_name = "custom_components"
    if root_module_name not in sys.modules:
        root_module = types.ModuleType(root_module_name)
        root_module.__path__ = [str(ROOT / root_module_name)]
        sys.modules[root_module_name] = root_module

    package = sys.modules.get(PACKAGE_NAME)
    if package is None:
        package = types.ModuleType(PACKAGE_NAME)
        package.__path__ = [str(COMPONENT_DIR)]
        package.__package__ = root_module_name
        sys.modules[PACKAGE_NAME] = package

    module_filename = COMPONENT_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE_NAME}.{module_name}",
        module_filename,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[f"{PACKAGE_NAME}.{module_name}"] = module
    spec.loader.exec_module(module)
    return module


def _load_discovery_state():
    _load_component_module("const")
    _load_component_module("connection_helpers")
    _load_component_module("setup_scan")
    return _load_component_module("discovery_state")


class _FakeConfig:
    def __init__(self, root: Path) -> None:
        self._root = root

    def path(self, relative: str) -> str:
        return str(self._root / relative)


class _FakeHass:
    def __init__(self, root: Path) -> None:
        self.config = _FakeConfig(root)
        self.data: dict[str, object] = {}
        self.executor_job_count = 0

    async def async_add_executor_job(self, func, *args):
        self.executor_job_count += 1
        return func(*args)


class TestDiscoveryState(unittest.TestCase):
    """Validate discovery confidence, persistence and diagnostics."""

    def setUp(self) -> None:
        self.discovery = _load_discovery_state()

    def test_zeroconf_record_scores_realistic_payload(self) -> None:
        info = types.SimpleNamespace(
            host="192.0.2.124",
            hostname="dhe-ja06.local.",
            name="DHE Connect DHE-JA06._ste-dhe._tcp.local.",
            ip_address="192.0.2.124",
        )

        record = self.discovery.zeroconf_discovery_record(
            host="192.0.2.124",
            port=8443,
            name="DHE Connect DHE-JA06",
            discovery_info=info,
        )

        self.assertEqual(record.source, "zeroconf")
        self.assertGreaterEqual(record.confidence, 80)
        self.assertEqual(record.preferred_identity_source, "hostname")
        self.assertFalse(record.identity_conflicts)
        self.assertFalse(record.hard_conflict)

    def test_zeroconf_record_detects_hard_identity_conflict(self) -> None:
        info = types.SimpleNamespace(
            host="192.0.2.124",
            hostname="other-dhe.local.",
            name="DHE-JA06._ste-dhe._tcp.local.",
            ip_address="192.0.2.200",
        )

        record = self.discovery.zeroconf_discovery_record(
            host="192.0.2.124",
            port=8443,
            name="DHE-JA06",
            discovery_info=info,
        )

        self.assertIn("host_ip_differs_from_ip_address", record.identity_conflicts)
        self.assertTrue(record.hard_conflict)
        self.assertLess(record.confidence, 80)

    def test_cache_persists_records_and_exposes_health(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            hass = _FakeHass(root)
            info = types.SimpleNamespace(
                host="192.0.2.124",
                hostname="dhe-ja06.local.",
                name="DHE-JA06._ste-dhe._tcp.local.",
                ip_address="192.0.2.124",
            )
            record = self.discovery.zeroconf_discovery_record(
                host="192.0.2.124",
                port=8443,
                name="DHE-JA06",
                discovery_info=info,
            )

            asyncio.run(
                self.discovery.async_record_discovery(
                    hass,
                    record,
                    result="prompted",
                    prompted=True,
                )
            )

            cache_path = root / self.discovery.DISCOVERY_CACHE_FILE
            self.assertTrue(cache_path.exists())
            cached_payload = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(cached_payload["version"], 1)

            restarted_hass = _FakeHass(root)
            self.assertTrue(
                asyncio.run(
                    self.discovery.async_recent_discovery_prompt_seen(
                        restarted_hass,
                        record,
                    )
                )
            )
            choices = self.discovery.cached_discovery_choices(restarted_hass)
            self.assertEqual(len(choices), 1)
            self.assertEqual(choices[0].host, "192.0.2.124")

            health = self.discovery.discovery_health_diagnostics(restarted_hass)
            self.assertTrue(health["loaded"])
            self.assertEqual(health["recent_record_count"], 1)
            self.assertEqual(health["sources"], {"zeroconf": 1})
            self.assertEqual(
                health["preferred_identity_sources"],
                {"hostname": 1},
            )
            self.assertEqual(health["confidence"]["high"], 1)

    def test_recent_prompt_suppression_survives_repeated_unresolved_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            hass = _FakeHass(Path(temp_dir))
            info = types.SimpleNamespace(
                host="192.0.2.124",
                hostname="dhe-ja06.local.",
                name="DHE-JA06._ste-dhe._tcp.local.",
                ip_address="192.0.2.124",
            )
            record = self.discovery.zeroconf_discovery_record(
                host="192.0.2.124",
                port=8443,
                name="DHE-JA06",
                discovery_info=info,
            )

            for _ in range(2):
                asyncio.run(
                    self.discovery.async_record_discovery(
                        hass,
                        record,
                        result="prompted",
                        prompted=True,
                    )
                )

            self.assertTrue(
                asyncio.run(
                    self.discovery.async_recent_discovery_prompt_seen(hass, record)
                )
            )
            payload = asyncio.run(self.discovery.async_load_discovery_cache(hass))
            cached = payload["records"][record.key]
            self.assertEqual(cached["prompt_count"], 2)

    def test_pruning_preserves_recent_zeroconf_prompt_over_scan_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            hass = _FakeHass(Path(temp_dir))
            info = types.SimpleNamespace(
                host="192.0.2.124",
                hostname="dhe-ja06.local.",
                name="DHE-JA06._ste-dhe._tcp.local.",
                ip_address="192.0.2.124",
            )
            record = self.discovery.zeroconf_discovery_record(
                host="192.0.2.124",
                port=8443,
                name="DHE-JA06",
                discovery_info=info,
            )
            asyncio.run(
                self.discovery.async_record_discovery(
                    hass,
                    record,
                    result="prompted",
                    prompted=True,
                )
            )
            candidates = [
                self.discovery.DHEHostCandidate(
                    host=f"192.0.2.{index}",
                    port=8443,
                    evidence=("STE DHE App",),
                )
                for index in range(1, self.discovery.DISCOVERY_MAX_RECORDS + 1)
            ]

            asyncio.run(self.discovery.async_record_scan_discoveries(hass, candidates))

            payload = asyncio.run(self.discovery.async_load_discovery_cache(hass))
            records = payload["records"]
            self.assertEqual(len(records), self.discovery.DISCOVERY_MAX_RECORDS)
            self.assertIn(record.key, records)
            self.assertTrue(
                asyncio.run(
                    self.discovery.async_recent_discovery_prompt_seen(hass, record)
                )
            )

    def test_scan_candidate_is_recorded_for_health(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            hass = _FakeHass(Path(temp_dir))
            candidate = self.discovery.DHEHostCandidate(
                host="192.0.2.124",
                port=8443,
                evidence=("STE DHE App", "X-Powered-By=Express"),
            )

            asyncio.run(
                self.discovery.async_record_scan_discoveries(hass, [candidate])
            )

            health = self.discovery.discovery_health_diagnostics(hass)
            self.assertEqual(health["sources"], {"scan": 1})
            self.assertEqual(
                health["preferred_identity_sources"],
                {"scan_host": 1},
            )
            self.assertGreaterEqual(health["confidence"]["medium"], 1)

    def test_scan_discoveries_are_persisted_in_one_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            hass = _FakeHass(Path(temp_dir))
            candidates = [
                self.discovery.DHEHostCandidate(
                    host=f"192.0.2.{index}",
                    port=8443,
                    evidence=("STE DHE App",),
                )
                for index in range(10, 13)
            ]

            asyncio.run(self.discovery.async_record_scan_discoveries(hass, candidates))

            payload = asyncio.run(self.discovery.async_load_discovery_cache(hass))
            self.assertEqual(len(payload["records"]), 3)
            self.assertEqual(hass.executor_job_count, 2)

    def test_empty_scan_discoveries_do_not_create_cache_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            hass = _FakeHass(root)

            asyncio.run(self.discovery.async_record_scan_discoveries(hass, []))

            self.assertFalse((root / self.discovery.DISCOVERY_CACHE_FILE).exists())
            self.assertEqual(hass.executor_job_count, 0)

    def test_health_diagnostics_summarize_newest_records_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            hass = _FakeHass(Path(temp_dir))
            now = self.discovery.time.time()
            hass.data[self.discovery.DISCOVERY_DATA_KEY] = {
                "version": self.discovery.DISCOVERY_CACHE_VERSION,
                "records": {
                    "scan:old:8443": {
                        "source": "scan",
                        "last_seen": "2026-05-19T10:00:00Z",
                        "last_seen_ts": now - 10,
                        "confidence": 60,
                    },
                    "zeroconf:new:8443": {
                        "source": "zeroconf",
                        "last_seen": "2026-05-19T10:02:00Z",
                        "last_seen_ts": now,
                        "confidence": 90,
                    },
                },
            }

            health = self.discovery.discovery_health_diagnostics(hass)

            self.assertEqual(health["last_source"], "zeroconf")
            self.assertEqual(health["records"][0]["source"], "zeroconf")
            self.assertEqual(health["records"][1]["source"], "scan")


if __name__ == "__main__":
    unittest.main()
