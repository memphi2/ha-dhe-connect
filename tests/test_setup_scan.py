"""Tests for setup-time DHE scan helpers."""

from __future__ import annotations

from ipaddress import ip_network
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from homeassistant.const import CONF_HOST, CONF_PORT  # noqa: E402

from custom_components.stiebel_dhe_connect import setup_scan  # noqa: E402


class TestSetupScan(unittest.TestCase):
    """Validate pure setup-scan helper behavior."""

    def test_dhe_response_evidence_matches_dhe_web_ui_markers(self) -> None:
        evidence = setup_scan.dhe_response_evidence(
            b'<meta name="application-name" content="STE DHE App">',
            {"X-Powered-By": "Express"},
        )

        self.assertIn("STE DHE App", evidence)
        self.assertIn("X-Powered-By=Express", evidence)

    def test_dhe_response_evidence_ignores_generic_express_server(self) -> None:
        evidence = setup_scan.dhe_response_evidence(
            b"<html><title>Other device</title></html>",
            {"X-Powered-By": "Express"},
        )

        self.assertEqual(evidence, ())

    def test_ipv4_scan_networks_include_current_private_24_only(self) -> None:
        networks = setup_scan.ipv4_scan_networks(
            {"127.0.0.1", "169.254.1.1", "192.168.1.147"}
        )

        self.assertEqual(
            [str(network) for network in networks],
            ["192.168.1.0/24"],
        )

    def test_ipv4_scan_networks_preserve_input_order(self) -> None:
        networks = setup_scan.ipv4_scan_networks(
            ["192.168.1.10", "10.1.2.3", "192.168.1.20"]
        )

        self.assertEqual(
            [str(network) for network in networks],
            ["192.168.1.0/24", "10.1.2.0/24"],
        )

    def test_scan_hosts_caps_large_networks(self) -> None:
        networks = setup_scan.ipv4_scan_networks({"192.168.1.10"})

        self.assertEqual(
            setup_scan.scan_hosts(networks, max_hosts=2),
            ["192.168.1.1", "192.168.1.2"],
        )

    def test_scan_hosts_interleaves_networks_before_host_cap(self) -> None:
        hosts = setup_scan.scan_hosts(
            [ip_network("192.168.1.0/30"), ip_network("192.168.2.0/30")],
            max_hosts=4,
        )

        self.assertEqual(
            hosts,
            ["192.168.1.1", "192.168.2.1", "192.168.1.2", "192.168.2.2"],
        )

    def test_parse_scan_subnet_accepts_ipv4_address(self) -> None:
        network = setup_scan.parse_scan_subnet("192.168.2.123")

        self.assertEqual(str(network), "192.168.2.0/24")

    def test_parse_scan_subnet_accepts_ipv4_netmask(self) -> None:
        network = setup_scan.parse_scan_subnet("192.168.2.0 255.255.255.0")

        self.assertEqual(str(network), "192.168.2.0/24")

    def test_parse_scan_subnet_accepts_cidr(self) -> None:
        network = setup_scan.parse_scan_subnet("192.168.2.0/25")

        self.assertEqual(str(network), "192.168.2.0/25")

    def test_parse_scan_subnet_accepts_slash_netmask(self) -> None:
        network = setup_scan.parse_scan_subnet("192.168.2.0/255.255.255.0")

        self.assertEqual(str(network), "192.168.2.0/24")

    def test_parse_scan_subnet_rejects_large_networks(self) -> None:
        with self.assertRaisesRegex(ValueError, "scan_subnet_too_large"):
            setup_scan.parse_scan_subnet("192.168.0.0 255.255.0.0")

    def test_parse_scan_subnet_rejects_wildcard_masks(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid_scan_subnet"):
            setup_scan.parse_scan_subnet("192.168.2.0 0.0.0.255")

    def test_parse_scan_subnet_rejects_slash_wildcard_masks(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid_scan_subnet"):
            setup_scan.parse_scan_subnet("192.168.2.0/0.0.0.255")

    def test_parse_scan_subnet_rejects_non_contiguous_netmasks(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid_scan_subnet"):
            setup_scan.parse_scan_subnet("192.168.2.0 255.255.255.1")

    def test_parse_scan_subnet_rejects_non_private_networks(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid_scan_subnet"):
            setup_scan.parse_scan_subnet("8.8.8.0 255.255.255.0")

    def test_parse_scan_subnet_rejects_reserved_private_like_networks(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid_scan_subnet"):
            setup_scan.parse_scan_subnet("203.0.113.0 255.255.255.0")

    def test_setup_scan_subnet_input_accepts_split_network_netmask(self) -> None:
        scan_input = setup_scan.SetupScanSubnetInput(
            network_address="192.168.2.0",
            netmask="255.255.255.0",
        )

        self.assertEqual(str(scan_input.parse()), "192.168.2.0/24")

    def test_setup_scan_subnet_input_accepts_cidr(self) -> None:
        scan_input = setup_scan.SetupScanSubnetInput(cidr="192.168.2.0/25")

        self.assertEqual(str(scan_input.parse()), "192.168.2.0/25")

    def test_setup_scan_subnet_input_rejects_mixed_input_on_cidr_field(self) -> None:
        scan_input = setup_scan.SetupScanSubnetInput(
            network_address="192.168.2.0",
            netmask="255.255.255.0",
            cidr="192.168.2.0/24",
        )

        with self.assertRaisesRegex(ValueError, "invalid_scan_subnet"):
            scan_input.parse()
        self.assertEqual(
            scan_input.error_part(),
            setup_scan.SCAN_SUBNET_PART_CIDR,
        )

    def test_setup_scan_subnet_input_points_missing_network_to_address(self) -> None:
        scan_input = setup_scan.SetupScanSubnetInput(netmask="255.255.255.0")

        with self.assertRaisesRegex(ValueError, "invalid_scan_subnet"):
            scan_input.parse()
        self.assertEqual(
            scan_input.error_part(),
            setup_scan.SCAN_SUBNET_PART_NETWORK_ADDRESS,
        )

    def test_split_scan_subnet_suggestions(self) -> None:
        suggestions = setup_scan.split_scan_subnet_suggestions(
            ip_network("192.168.2.0/24"),
        )

        self.assertEqual(
            suggestions,
            {
                setup_scan.SCAN_SUBNET_PART_NETWORK_ADDRESS: "192.168.2.0",
                setup_scan.SCAN_SUBNET_PART_NETMASK: "255.255.255.0",
                setup_scan.SCAN_SUBNET_PART_CIDR: "",
            },
        )

    def test_candidate_defaults(self) -> None:
        defaults = setup_scan.candidate_defaults(
            setup_scan.DHEHostCandidate("192.0.2.124", 8443),
        )

        self.assertEqual(defaults, {CONF_HOST: "192.0.2.124", CONF_PORT: 8443})


if __name__ == "__main__":
    unittest.main()
