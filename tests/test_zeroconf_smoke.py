"""Tests for the real Zeroconf smoke helper."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import zeroconf_smoke


class TestZeroconfSmoke(unittest.TestCase):
    """Validate Zeroconf smoke helper behavior without multicast traffic."""

    def test_listener_matches_expected_port(self) -> None:
        listener = zeroconf_smoke.DHEZeroconfSmokeListener(expected_port=8443)
        zc = SimpleNamespace(
            get_service_info=lambda _type, _name, timeout: SimpleNamespace(port=8443)
        )

        listener.add_service(zc, "_ste-dhe._tcp.local.", "DHE._ste-dhe._tcp.local.")

        self.assertTrue(listener.matched.is_set())
        self.assertEqual(listener.seen_services, 1)
        self.assertEqual(listener.seen_ports, {8443})

    def test_listener_records_wrong_port_without_matching(self) -> None:
        listener = zeroconf_smoke.DHEZeroconfSmokeListener(expected_port=8443)
        zc = SimpleNamespace(
            get_service_info=lambda _type, _name, timeout: SimpleNamespace(port=9443)
        )

        listener.update_service(zc, "_ste-dhe._tcp.local.", "DHE._ste-dhe._tcp.local.")

        self.assertFalse(listener.matched.is_set())
        self.assertEqual(listener.seen_ports, {9443})

    def test_run_smoke_reports_match_without_exposing_hosts(self) -> None:
        class _Zeroconf:
            def get_service_info(self, _type, _name, timeout):  # noqa: ANN001
                return SimpleNamespace(port=8443)

            def close(self) -> None:
                pass

        class _Browser:
            def __init__(self, zc, type_, *, listener):  # noqa: ANN001
                listener.add_service(zc, type_, "PrivateHost._ste-dhe._tcp.local.")

            def cancel(self) -> None:
                pass

        with (
            patch("scripts.zeroconf_smoke.Zeroconf", _Zeroconf),
            patch("scripts.zeroconf_smoke.ServiceBrowser", _Browser),
        ):
            result = zeroconf_smoke.run_zeroconf_smoke(
                service_type="_ste-dhe._tcp.local.",
                timeout=0.01,
                expected_port=8443,
            )

        self.assertTrue(result.ok)
        self.assertIn("expected port 8443", result.message)
        self.assertNotIn("PrivateHost", result.message)

    def test_run_smoke_reports_wrong_port(self) -> None:
        class _Zeroconf:
            def get_service_info(self, _type, _name, timeout):  # noqa: ANN001
                return SimpleNamespace(port=9443)

            def close(self) -> None:
                pass

        class _Browser:
            def __init__(self, zc, type_, *, listener):  # noqa: ANN001
                listener.add_service(zc, type_, "PrivateHost._ste-dhe._tcp.local.")

            def cancel(self) -> None:
                pass

        with (
            patch("scripts.zeroconf_smoke.Zeroconf", _Zeroconf),
            patch("scripts.zeroconf_smoke.ServiceBrowser", _Browser),
        ):
            result = zeroconf_smoke.run_zeroconf_smoke(
                service_type="_ste-dhe._tcp.local.",
                timeout=0.01,
                expected_port=8443,
            )

        self.assertFalse(result.ok)
        self.assertIn("ports: 9443", result.message)
        self.assertNotIn("PrivateHost", result.message)

    def test_main_rejects_invalid_expected_port(self) -> None:
        self.assertEqual(
            zeroconf_smoke.main(["--expected-port", "0", "--timeout", "0.01"]),
            2,
        )


if __name__ == "__main__":
    unittest.main()
