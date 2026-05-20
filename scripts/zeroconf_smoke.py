"""Real Zeroconf/mDNS smoke check for DHE Connect discovery."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import threading
from typing import Any
from typing import Sequence

try:
    from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
except ModuleNotFoundError:  # pragma: no cover - optional dependency in real envs
    ServiceBrowser = None
    ServiceListener = Any
    Zeroconf = None


DHE_ZEROCONF_SERVICE = "_ste-dhe._tcp.local."
DEFAULT_DHE_PORT = 8443
DEFAULT_TIMEOUT_SECONDS = 20.0


@dataclass
class SmokeResult:
    """Result of one real Zeroconf smoke run."""

    ok: bool
    message: str


@dataclass
class DHEZeroconfSmokeListener(ServiceListener):
    """Collect matching DHE Zeroconf services without printing private hosts."""

    expected_port: int
    matched: threading.Event = field(default_factory=threading.Event)
    seen_services: int = 0
    seen_ports: set[int] = field(default_factory=set)

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Handle an added DNS-SD service."""
        self._record_service(zc, type_, name)

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Handle a changed DNS-SD service."""
        self._record_service(zc, type_, name)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Handle a removed DNS-SD service."""

    def _record_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name, timeout=1000)
        if info is None:
            return
        self.seen_services += 1
        try:
            port = int(info.port)
        except (TypeError, ValueError):
            return
        self.seen_ports.add(port)
        if port == self.expected_port:
            self.matched.set()


def validate_timeout(value: float) -> float:
    """Return a positive timeout."""
    timeout = float(value)
    if timeout <= 0:
        raise ValueError("timeout must be greater than 0")
    return timeout


def validate_port(value: int) -> int:
    """Return a valid TCP port."""
    port = int(value)
    if port < 1 or port > 65535:
        raise ValueError("port must be between 1 and 65535")
    return port


def run_zeroconf_smoke(
    *,
    service_type: str,
    timeout: float,
    expected_port: int,
) -> SmokeResult:
    """Listen for a real DHE Zeroconf advertisement."""
    if Zeroconf is None or ServiceBrowser is None:
        return SmokeResult(
            False,
            "zeroconf package is not installed; install `zeroconf` to run this smoke.",
        )
    listener = DHEZeroconfSmokeListener(expected_port=expected_port)
    zeroconf = Zeroconf()  # type: ignore[misc]
    browser = ServiceBrowser(zeroconf, service_type, listener=listener)  # type: ignore[misc]
    try:
        listener.matched.wait(timeout)
    finally:
        browser.cancel()
        zeroconf.close()

    if listener.matched.is_set():
        return SmokeResult(
            True,
            f"found {service_type} Zeroconf service on expected port {expected_port}",
        )
    if listener.seen_services:
        ports = ", ".join(str(port) for port in sorted(listener.seen_ports)) or "unknown"
        return SmokeResult(
            False,
            f"saw {listener.seen_services} {service_type} service(s), but not on port {expected_port}; ports: {ports}",
        )
    return SmokeResult(
        False,
        f"no {service_type} Zeroconf service seen within {timeout:g}s",
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check that a real DHE Zeroconf/mDNS advertisement is visible.",
    )
    parser.add_argument("--service-type", default=DHE_ZEROCONF_SERVICE)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--expected-port", type=int, default=DEFAULT_DHE_PORT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Zeroconf smoke check."""
    args = _parse_args(argv)
    try:
        timeout = validate_timeout(args.timeout)
        expected_port = validate_port(args.expected_port)
    except ValueError as err:
        print(f"FAIL: {err}")
        return 2

    result = run_zeroconf_smoke(
        service_type=str(args.service_type),
        timeout=timeout,
        expected_port=expected_port,
    )
    print(("PASS: " if result.ok else "FAIL: ") + result.message)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
