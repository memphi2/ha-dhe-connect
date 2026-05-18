"""Setup-time DHE web-interface scan helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network, ip_address, ip_network
import socket
from typing import Any

import aiohttp

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DEFAULT_PORT
from .connection_helpers import host_for_url

DHE_SCAN_PORT = DEFAULT_PORT
DHE_SCAN_MAX_HOSTS = 512
DHE_SCAN_CONCURRENCY = 256
DHE_SCAN_TOTAL_TIMEOUT_SECONDS = 0.45
DHE_SCAN_CONNECT_TIMEOUT_SECONDS = 0.25
DHE_SCAN_MIN_PREFIX_LENGTH = 24
RFC1918_NETWORKS = (
    IPv4Network("10.0.0.0/8"),
    IPv4Network("172.16.0.0/12"),
    IPv4Network("192.168.0.0/16"),
)
DHE_MARKERS = (
    "STE DHE App",
    "ste.dhe",
    "ste-dhe",
    "manifest-1.9.00.appcache",
    "assets/ste-dhe",
)


@dataclass(frozen=True)
class DHEHostCandidate:
    """One DHE-like web-interface candidate found during setup scan."""

    host: str
    port: int
    evidence: tuple[str, ...] = ()


def _is_rfc1918_address(address: IPv4Address) -> bool:
    """Return True for routed private IPv4 addresses."""
    return any(address in network for network in RFC1918_NETWORKS)


def _is_rfc1918_network(network: IPv4Network) -> bool:
    """Return True for routed private IPv4 networks."""
    return any(network.subnet_of(private) for private in RFC1918_NETWORKS)


def _netmask_prefix_length(mask_text: str) -> int:
    """Return the prefix length for a dotted IPv4 netmask."""
    try:
        mask = IPv4Address(mask_text)
    except ValueError as err:
        raise ValueError("invalid_scan_subnet") from err

    inverted = (~int(mask)) & 0xFFFFFFFF
    if inverted & (inverted + 1):
        raise ValueError("invalid_scan_subnet")
    return 32 - inverted.bit_length()


def _parse_ipv4_network(text: str) -> IPv4Network:
    """Parse an IPv4 network while rejecting wildcard dotted masks."""
    if "/" not in text:
        parsed_address = ip_address(text)
        if not isinstance(parsed_address, IPv4Address):
            raise ValueError("invalid_scan_subnet")
        parsed_network = ip_network(f"{parsed_address}/24", strict=False)
    else:
        address_text, mask_text = text.split("/", maxsplit=1)
        if "." in mask_text:
            prefix_length = _netmask_prefix_length(mask_text)
            parsed_network = ip_network(
                f"{address_text}/{prefix_length}",
                strict=False,
            )
        else:
            parsed_network = ip_network(text, strict=False)
    if not isinstance(parsed_network, IPv4Network):
        raise ValueError("invalid_scan_subnet")
    return parsed_network


def dhe_response_evidence(body: bytes, headers: Any) -> tuple[str, ...]:
    """Return evidence markers that make a response look like the DHE web UI."""
    text = body.decode("utf-8", errors="ignore").lower()
    evidence = [
        marker
        for marker in DHE_MARKERS
        if marker.lower() in text
    ]
    try:
        powered_by = str(headers.get("X-Powered-By", ""))
    except AttributeError:
        powered_by = ""
    if not powered_by and isinstance(headers, dict):
        powered_by = str(headers.get("x-powered-by") or "")
    if powered_by.lower() == "express" and evidence:
        evidence.append("X-Powered-By=Express")
    return tuple(evidence)


def ipv4_scan_networks(addresses: Iterable[str]) -> list[IPv4Network]:
    """Return current local /24 networks to scan from local IPv4 addresses."""
    networks: list[IPv4Network] = []
    seen: set[IPv4Network] = set()
    for address in addresses:
        try:
            parsed = ip_address(address)
        except ValueError:
            continue
        if (
            not isinstance(parsed, IPv4Address)
            or not _is_rfc1918_address(parsed)
            or parsed.is_loopback
            or parsed.is_link_local
            or parsed.is_unspecified
        ):
            continue
        octets = [int(part) for part in str(parsed).split(".")]
        network = ip_network(
            f"{octets[0]}.{octets[1]}.{octets[2]}.0/24",
            strict=False,
        )
        if isinstance(network, IPv4Network) and network not in seen:
            seen.add(network)
            networks.append(network)
    return networks


def parse_scan_subnet(value: Any) -> IPv4Network | None:
    """Parse an optional private IPv4 subnet or host address for setup scanning."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parts = text.split()
        if len(parts) == 2:
            prefix_length = _netmask_prefix_length(parts[1])
            parsed_network = ip_network(f"{parts[0]}/{prefix_length}", strict=False)
        elif len(parts) > 2:
            raise ValueError("invalid_scan_subnet")
        else:
            parsed_network = _parse_ipv4_network(text)
    except ValueError as err:
        raise ValueError("invalid_scan_subnet") from err

    if not isinstance(parsed_network, IPv4Network):
        raise ValueError("invalid_scan_subnet")
    if (
        not _is_rfc1918_network(parsed_network)
        or parsed_network.is_loopback
        or parsed_network.is_link_local
        or parsed_network.network_address.is_unspecified
    ):
        raise ValueError("invalid_scan_subnet")
    if parsed_network.prefixlen < DHE_SCAN_MIN_PREFIX_LENGTH:
        raise ValueError("scan_subnet_too_large")
    return parsed_network


def scan_hosts(networks: Sequence[IPv4Network], *, max_hosts: int) -> list[str]:
    """Expand networks into host addresses, capped for setup responsiveness."""
    hosts: list[str] = []
    iterators: list[Iterator[IPv4Address]] = [network.hosts() for network in networks]
    while iterators and len(hosts) < max_hosts:
        next_round: list[Iterator[IPv4Address]] = []
        for iterator in iterators:
            try:
                host = next(iterator)
            except StopIteration:
                continue
            hosts.append(str(host))
            if len(hosts) >= max_hosts:
                break
            next_round.append(iterator)
        iterators = next_round
    return hosts


def local_ipv4_addresses_from_hass(hass: HomeAssistant) -> list[str]:
    """Collect local IPv4 addresses from HA configuration and socket fallback."""
    addresses: list[str] = []
    seen: set[str] = set()

    def _add_address(address: Any) -> None:
        text = str(address or "").strip()
        if text and text not in seen:
            seen.add(text)
            addresses.append(text)

    api = getattr(getattr(hass, "config", None), "api", None)
    if api is not None:
        local_ip = getattr(api, "local_ip", None)
        _add_address(local_ip)
    internal_url = getattr(getattr(hass, "config", None), "internal_url", None)
    if internal_url:
        try:
            from yarl import URL  # noqa: PLC0415

            host = URL(str(internal_url)).host
        except (TypeError, ValueError):
            host = None
        if host:
            _add_address(host)
    try:
        for family, _type, _proto, _canonname, sockaddr in socket.getaddrinfo(
            socket.gethostname(),
            None,
            family=socket.AF_INET,
        ):
            if family == socket.AF_INET:
                _add_address(sockaddr[0])
    except OSError:
        pass
    return addresses


async def _probe_host(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    timeout: aiohttp.ClientTimeout,
) -> DHEHostCandidate | None:
    url = f"http://{host_for_url(host)}:{port}/"
    try:
        async with session.get(url, timeout=timeout) as response:
            body = await response.content.read(4096)
            evidence = dhe_response_evidence(body, response.headers)
    except (aiohttp.ClientError, TimeoutError, OSError):
        return None
    if not evidence:
        return None
    return DHEHostCandidate(host=host, port=port, evidence=evidence)


async def async_scan_dhe_hosts(
    hass: HomeAssistant,
    *,
    networks: Sequence[IPv4Network] | None = None,
    port: int = DHE_SCAN_PORT,
    max_hosts: int = DHE_SCAN_MAX_HOSTS,
) -> list[DHEHostCandidate]:
    """Scan selected setup networks for DHE-like web interfaces."""
    if networks is None:
        addresses = await hass.async_add_executor_job(local_ipv4_addresses_from_hass, hass)
        networks = ipv4_scan_networks(addresses)
    hosts = scan_hosts(networks, max_hosts=max_hosts)
    if not hosts:
        return []

    session = async_get_clientsession(hass)
    timeout = aiohttp.ClientTimeout(
        total=DHE_SCAN_TOTAL_TIMEOUT_SECONDS,
        connect=DHE_SCAN_CONNECT_TIMEOUT_SECONDS,
        sock_connect=DHE_SCAN_CONNECT_TIMEOUT_SECONDS,
        sock_read=DHE_SCAN_CONNECT_TIMEOUT_SECONDS,
    )
    semaphore = asyncio.Semaphore(DHE_SCAN_CONCURRENCY)

    async def _bounded_probe(host: str) -> DHEHostCandidate | None:
        async with semaphore:
            return await _probe_host(session, host, port, timeout)

    results = await asyncio.gather(*(_bounded_probe(host) for host in hosts))
    candidates = [result for result in results if result is not None]
    return sorted(candidates, key=lambda candidate: candidate.host)


def candidate_defaults(candidate: DHEHostCandidate | None) -> dict[str, Any]:
    """Return form defaults for a scan candidate."""
    if candidate is None:
        return {}
    return {
        CONF_HOST: candidate.host,
        CONF_PORT: candidate.port,
    }
