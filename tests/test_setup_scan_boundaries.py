"""Setup scan validation, bounded probing and session ownership."""

import asyncio
from ipaddress import ip_network
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.stiebel_dhe_connect import setup_scan as scan


@pytest.mark.parametrize(
    "text", ["::1", "2001:db8::/64", "192.0.2.1 invalid", "one two three"]
)
def test_invalid_subnets_are_rejected(text):
    with pytest.raises(ValueError, match="invalid_scan_subnet"):
        scan.parse_scan_subnet(text)


def test_empty_partial_inputs_and_exhausted_networks():
    assert scan.parse_scan_subnet("") is None
    assert scan.SetupScanSubnetInput().error_part() == "cidr"
    assert (
        scan.SetupScanSubnetInput(network_address="192.0.2.1").error_part() == "netmask"
    )
    assert scan.candidate_defaults(None) == {}
    assert scan.scan_hosts([], max_hosts=0) == []
    assert scan.scan_hosts([ip_network("192.0.2.0/30")], max_hosts=10) == [
        "192.0.2.1",
        "192.0.2.2",
    ]
    assert scan.ipv4_scan_networks(["invalid", "::1"]) == []
    assert scan.dhe_response_evidence("ste.dhe", None) == ("ste.dhe",)
    assert scan.dhe_response_evidence("ste.dhe", {"x-powered-by": "Express"}) == (
        "ste.dhe",
        "X-Powered-By=Express",
    )


@pytest.mark.parametrize(
    "language,scanned,found,available,failed,expected",
    [
        ("de", False, 0, 0, False, "Host/IP"),
        ("de", True, 0, 0, False, "kein DHE"),
        ("de", True, 1, 0, False, "bereits konfiguriert"),
        ("de", True, 2, 2, False, "2 DHE-Kandidaten"),
        ("en", True, 0, 0, True, "failed"),
        ("en", True, 0, 0, False, "No DHE"),
        ("en", True, 1, 0, False, "already configured"),
        ("en", True, 1, 1, False, "one DHE"),
    ],
)
def test_scan_status_describes_actionable_result(
    language, scanned, found, available, failed, expected
):
    assert expected in scan.setup_scan_status_text(
        language, scanned=scanned, found=found, available=available, failed=failed
    )


@pytest.mark.parametrize("internal_url", ["http://192.0.2.2:8123", "http://[invalid"])
@pytest.mark.parametrize("dns_failure", [False, True])
def test_local_address_collection_deduplicates_and_tolerates_lookup_failure(
    monkeypatch, internal_url, dns_failure
):
    hass = SimpleNamespace(
        config=SimpleNamespace(
            api=SimpleNamespace(local_ip="192.0.2.1"), internal_url=internal_url
        )
    )
    lookup = Mock(
        side_effect=OSError() if dns_failure else None,
        return_value=[
            (scan.socket.AF_INET, 0, 0, "", ("192.0.2.1", 0)),
            (scan.socket.AF_INET, 0, 0, "", ("192.0.2.3", 0)),
        ],
    )
    monkeypatch.setattr(scan.socket, "getaddrinfo", lookup)
    expected = ["192.0.2.1"]
    if "invalid" not in internal_url:
        expected.append("192.0.2.2")
    if not dns_failure:
        expected.append("192.0.2.3")
    assert scan.local_ipv4_addresses_from_hass(hass) == expected


@pytest.mark.parametrize(
    "status,encoding,body,error,found",
    [
        (200, "identity", b"ste.dhe", None, True),
        (200, "identity", b"unrelated", None, False),
        (302, "identity", b"ste.dhe", None, False),
        (200, "gzip", b"ste.dhe", None, False),
        (200, "identity", b"", TimeoutError(), False),
        (200, "identity", b"", OSError(), False),
    ],
)
async def test_probe_is_bounded_and_requires_uncompressed_device_evidence(
    status, encoding, body, error, found
):
    response = SimpleNamespace(
        status=status,
        headers={"Content-Encoding": encoding},
        content=SimpleNamespace(read=AsyncMock(return_value=body, side_effect=error)),
    )
    context = AsyncMock()
    context.__aenter__.return_value = response
    session = SimpleNamespace(get=Mock(return_value=context))
    result = await scan._probe_host(
        session, "192.0.2.1", 8443, scan.aiohttp.ClientTimeout(total=1)
    )
    assert (result is not None) is found
    assert session.get.call_args.kwargs["allow_redirects"] is False
    assert session.get.call_args.kwargs["auto_decompress"] is False
    if status == 200 and encoding == "identity":
        response.content.read.assert_awaited_once_with(4096)
    else:
        response.content.read.assert_not_awaited()


@pytest.mark.parametrize("owns_session", [False, True])
@pytest.mark.parametrize("failure", [False, True])
async def test_scan_bounds_concurrency_and_closes_only_owned_sessions(
    monkeypatch, owns_session, failure
):
    session = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(
        scan,
        "async_get_clientsession",
        Mock(
            side_effect=RuntimeError("not ready") if owns_session else None,
            return_value=session,
        ),
    )
    monkeypatch.setattr(scan.aiohttp, "ClientSession", Mock(return_value=session))
    monkeypatch.setattr(scan, "DHE_SCAN_CONCURRENCY", 1)
    active = maximum = 0

    async def probe(_session, host, port, timeout):
        nonlocal active, maximum
        assert _session is session
        assert timeout.total == scan.DHE_SCAN_TOTAL_TIMEOUT_SECONDS
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        active -= 1
        if failure:
            raise ValueError("unexpected probe error")
        return scan.DHEHostCandidate(host, port)

    monkeypatch.setattr(scan, "_probe_host", probe)
    networks = [ip_network("192.0.2.0/30")]
    if failure:
        with pytest.raises(ValueError, match="unexpected probe"):
            await scan.async_scan_dhe_hosts(object(), networks=networks)
        await asyncio.sleep(0)
    else:
        result = await scan.async_scan_dhe_hosts(object(), networks=networks)
        assert [candidate.host for candidate in result] == ["192.0.2.1", "192.0.2.2"]
    assert maximum == 1
    assert session.close.await_count == int(owns_session)


async def test_scan_derives_networks_off_loop_and_skips_empty_targets(monkeypatch):
    hass = SimpleNamespace(async_add_executor_job=AsyncMock(return_value=["192.0.2.1"]))
    session = Mock()
    monkeypatch.setattr(scan, "async_get_clientsession", session)
    assert await scan.async_scan_dhe_hosts(hass) == []
    hass.async_add_executor_job.assert_awaited_once_with(
        scan.local_ipv4_addresses_from_hass, hass
    )
    session.assert_not_called()
