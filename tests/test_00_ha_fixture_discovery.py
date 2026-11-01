"""Real Home Assistant integration regression tests."""

from __future__ import annotations

import importlib
import json
import types
from ipaddress import ip_network
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries, loader
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
)
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import (
    issue_registry as ir,
)

from tests.ha_test_support import (
    DEFAULT_PORT,
    DOMAIN,
    PAIRING_TOKEN,
    FakeDHEEngineIOServer,
    _async_test_home_assistant,
    _build_mock_entry,
    _clear_loaded_integration_modules,
    _ensure_network_loaded,
    _isolate_discovery_cache,  # noqa: F401 - registers the pytest fixture
    _schema_defaults,
    _schema_suggested_values,
    _zeroconf_info,
)

pytestmark = pytest.mark.asyncio


async def test_ha_shutdown_flushes_coalesced_discovery_cache(tmp_path) -> None:
    _clear_loaded_integration_modules()
    discovery = importlib.import_module(f"custom_components.{DOMAIN}.discovery_state")
    record = discovery.DiscoveryRecord(
        source="scan", key="device", host="192.0.2.1", port=8443,
        name="Test", confidence=80, preferred_identity_source="scan_host",
    )
    path = tmp_path / discovery.DISCOVERY_CACHE_FILE
    async with _async_test_home_assistant(config_dir=str(tmp_path)) as hass:
        for _ in range(100):
            await discovery.async_record_discovery(hass, record)
        writer = hass.data[discovery.DISCOVERY_WRITER_KEY]
        assert writer.handle is not None
        assert writer.task is None
        assert not path.exists()
    assert writer.handle is None
    assert writer.task is None
    assert not writer.dirty
    assert json.loads(path.read_text())["records"]["device"]["seen_count"] == 100


@pytest.fixture
def flow_only():
    """Do not connect to documentation addresses after flow entry creation."""
    with patch.object(config_entries.ConfigEntries, "async_setup", AsyncMock(return_value=True)):
        yield


async def test_config_flow_scan_choice_prefills_manual_form_with_real_hass_fixture() -> None:
    """Run optional setup scan progress before the manual setup form."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        scan = AsyncMock(
            return_value=[
                types.SimpleNamespace(
                    host="192.0.2.124",
                    port=DEFAULT_PORT,
                    evidence=("STE DHE App",),
                )
            ]
        )
        with (
            patch.object(config_flow, "async_scan_dhe_hosts", scan),
            patch.object(
                config_flow,
                "local_ipv4_addresses_from_hass",
                return_value=["192.168.50.10"],
            ),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "user"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {config_flow.CONF_SETUP_MODE: config_flow.SETUP_MODE_SCAN},
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "subnet_scan"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    config_flow.CONF_SCAN_SUBNET_MODE: (
                        config_flow.SCAN_SUBNET_MODE_NETWORK_MASK
                    )
                },
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "subnet_scan_network_mask"
            suggested = _schema_suggested_values(result["data_schema"])
            assert suggested[config_flow.CONF_SCAN_NETWORK_ADDRESS] == "192.168.50.0"
            assert suggested[config_flow.CONF_SCAN_NETMASK] == "255.255.255.0"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    config_flow.CONF_SCAN_NETWORK_ADDRESS: "192.168.50.0",
                    config_flow.CONF_SCAN_NETMASK: "255.255.255.0",
                },
            )
            assert result["type"] is FlowResultType.SHOW_PROGRESS
            assert result["progress_action"] == "scan_dhe"

            await hass.async_block_till_done()
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
            )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "manual"
        defaults = _schema_defaults(result["data_schema"])
        assert defaults[CONF_HOST] == "192.0.2.124"
        assert defaults[CONF_PORT] == DEFAULT_PORT
        scan.assert_awaited_once_with(
            hass,
            networks=[ip_network("192.168.50.0/24")],
            port=DEFAULT_PORT,
        )



async def test_config_flow_current_subnet_scan_progress_with_real_hass_fixture() -> None:
    """Exercise HA config-flow progress handling for the current-subnet scan."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        scan = AsyncMock(return_value=[])
        with patch.object(config_flow, "async_scan_dhe_hosts", scan):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "user"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {config_flow.CONF_SETUP_MODE: config_flow.SETUP_MODE_SCAN},
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "subnet_scan"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    config_flow.CONF_SCAN_SUBNET_MODE: (
                        config_flow.SCAN_SUBNET_MODE_CURRENT
                    ),
                    config_flow.CONF_SCAN_PORT: DEFAULT_PORT,
                },
            )
            assert result["type"] is FlowResultType.SHOW_PROGRESS
            assert result["step_id"] == "network_scan"
            assert result["progress_action"] == "scan_dhe"

            await hass.async_block_till_done()
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "manual"

        defaults = _schema_defaults(result["data_schema"])
        assert defaults[CONF_PORT] == DEFAULT_PORT
        assert "host" not in defaults or defaults[CONF_HOST] in (None, "")
        assert "No DHE" in result["description_placeholders"]["scan_status"]
        scan.assert_awaited_once_with(hass, networks=None, port=DEFAULT_PORT)



@pytest.mark.usefixtures("flow_only")
async def test_scan_prefilled_flow_uses_pairing_unique_id_with_real_hass_fixture() -> None:
    """Create a scanned entry with the same MAC unique-id path as Zeroconf."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        scan = AsyncMock(
            return_value=[
                types.SimpleNamespace(
                    host="192.0.2.124",
                    port=DEFAULT_PORT,
                    evidence=("STE DHE App",),
                )
            ]
        )
        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(
            return_value=config_flow.SetupPairingResult(
                unique_id="aa:bb:cc:dd:ee:ff",
            )
        )
        with (
            patch.object(config_flow, "async_scan_dhe_hosts", scan),
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {config_flow.CONF_SETUP_MODE: config_flow.SETUP_MODE_SCAN},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    config_flow.CONF_SCAN_SUBNET_MODE: (
                        config_flow.SCAN_SUBNET_MODE_CURRENT
                    )
                },
            )
            assert result["type"] is FlowResultType.SHOW_PROGRESS

            await hass.async_block_till_done()
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "manual"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    CONF_HOST: "192.0.2.124",
                    CONF_PORT: DEFAULT_PORT,
                    CONF_NAME: "Scanned DHE",
                    config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55",
                },
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "pairing_confirm"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {},
            )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["result"].unique_id == "aa:bb:cc:dd:ee:ff"
        assert result["data"][CONF_HOST] == "192.0.2.124"
        scan.assert_awaited_once()
        can_connect.assert_awaited_once_with(hass, "192.0.2.124", DEFAULT_PORT)
        validate_pairing.assert_awaited_once()



@pytest.mark.usefixtures("flow_only")
async def test_zeroconf_flow_collects_tmax_then_creates_entry_after_pairing() -> None:
    """Run Zeroconf setup without creating an entry before pairing succeeds."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(
            return_value=config_flow.SetupPairingResult(
                unique_id="aa:bb:cc:dd:ee:ff",
            )
        )
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info("DHE-JA06.local.", DEFAULT_PORT),
            )

            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "zeroconf_confirm"
            defaults = _schema_defaults(result["data_schema"])
            assert defaults == {config_flow.CONF_INTERNAL_SCALD_PROTECTION: "60"}
            assert hass.config_entries.async_entries(DOMAIN) == []

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55"},
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "pairing_confirm"
            assert hass.config_entries.async_entries(DOMAIN) == []

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={},
            )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "DHE-JA06"
        assert result["data"] == {
            CONF_HOST: "192.0.2.124",
            CONF_PORT: DEFAULT_PORT,
            CONF_NAME: "DHE-JA06",
            config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55",
        }
        assert result["result"].unique_id == "aa:bb:cc:dd:ee:ff"
        can_connect.assert_awaited_once_with(hass, "192.0.2.124", DEFAULT_PORT)
        validate_pairing.assert_awaited_once()



async def test_zeroconf_flow_pairs_against_fake_dhe_engineio_server() -> None:
    """Run Zeroconf -> Tmax -> pairing -> entry creation against Fake-DHE."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    client_pairing = importlib.import_module(
        f"custom_components.{DOMAIN}.client_pairing"
    )
    protocol = importlib.import_module(f"custom_components.{DOMAIN}.protocol")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        await _ensure_network_loaded(hass)
        async with FakeDHEEngineIOServer(protocol.NS) as server:
            server.queue_pairing_request()
            server.queue_pairing_result(True)
            server.queue_token_response(PAIRING_TOKEN)
            server.queue_authentication()
            server.queue_device_info()

            with (
                patch.object(client_pairing.persistent_notification, "async_create"),
                patch.object(client_pairing.persistent_notification, "async_dismiss"),
            ):
                result = await hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": config_entries.SOURCE_ZEROCONF},
                    data=_zeroconf_info(
                        "DHE-JA06.local.",
                        server.port,
                        host=server.host,
                        ip=server.host,
                    ),
                )

                assert result["type"] is FlowResultType.FORM
                assert result["step_id"] == "zeroconf_confirm"
                assert hass.config_entries.async_entries(DOMAIN) == []

                result = await hass.config_entries.flow.async_configure(
                    result["flow_id"],
                    user_input={config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55"},
                )
                assert result["type"] is FlowResultType.FORM
                assert result["step_id"] == "pairing_confirm"

                result = await hass.config_entries.flow.async_configure(
                    result["flow_id"],
                    user_input={},
                )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "DHE-JA06"
        assert result["data"][CONF_HOST] == server.host
        assert result["data"][CONF_PORT] == server.port
        assert result["data"][config_flow.CONF_INTERNAL_SCALD_PROTECTION] == "55"
        assert result["result"].unique_id == "aa:bb:cc:dd:ee:ff"
        assert any(
            '"token":""' in packet and '["token_request"' in packet
            for packet in server.posted_packets
        )
        assert any(PAIRING_TOKEN in packet for packet in server.posted_packets)



@pytest.mark.parametrize(
    ("discovery_kwargs", "expected_host", "expected_port", "expected_title"),
    [
        (
            {
                "hostname": "dhe-ja06.local.",
                "port": DEFAULT_PORT,
                "host": "dhe-ja06.local.",
                "name": "DHE Connect DHE-JA06._ste-dhe._tcp.local.",
            },
            "dhe-ja06.local",
            DEFAULT_PORT,
            "DHE Connect DHE-JA06",
        ),
        (
            {"hostname": "dhe-ja06.local.", "port": DEFAULT_PORT, "host": None},
            "dhe-ja06.local",
            DEFAULT_PORT,
            "dhe-ja06",
        ),
        (
            {
                "hostname": "dhe-ja06.local.",
                "port": DEFAULT_PORT,
                "host": "192.0.2.125",
                "name": "DHE-JA06.local.",
                "ip": "192.0.2.125",
            },
            "192.0.2.125",
            DEFAULT_PORT,
            "DHE-JA06",
        ),
        (
            {
                "hostname": "dhe-ja06.local.",
                "port": DEFAULT_PORT,
                "host": "192.0.2.126",
                "name": "DHE-JA06._ste-dhe._tcp.local.",
                "ip": "192.0.2.126",
            },
            "192.0.2.126",
            DEFAULT_PORT,
            "DHE-JA06",
        ),
        (
            {
                "hostname": None,
                "port": DEFAULT_PORT,
                "host": "192.0.2.127",
                "name": "DHE-JA06.local.",
                "ip": "192.0.2.127",
            },
            "192.0.2.127",
            DEFAULT_PORT,
            "DHE-JA06",
        ),
        (
            {
                "hostname": "dhe-ja06.local.",
                "port": None,
                "host": "192.0.2.128",
                "ip": "192.0.2.128",
            },
            "192.0.2.128",
            DEFAULT_PORT,
            "dhe-ja06",
        ),
    ],
)
@pytest.mark.usefixtures("flow_only")
async def test_zeroconf_flow_accepts_realistic_discovery_payload_variants(
    discovery_kwargs: dict[str, Any],
    expected_host: str,
    expected_port: int,
    expected_title: str,
) -> None:
    """Verify real-world mDNS payload shapes normalize to one setup path."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(
            return_value=config_flow.SetupPairingResult(
                unique_id=f"unique-{expected_host}",
            )
        )
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info(**discovery_kwargs),
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "zeroconf_confirm"
            can_connect.assert_awaited_once_with(hass, expected_host, expected_port)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55"},
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "pairing_confirm"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={},
            )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == expected_title
        assert result["data"][CONF_HOST] == expected_host
        assert result["data"][CONF_PORT] == expected_port
        validate_pairing.assert_awaited_once()



@pytest.mark.parametrize(
    "port",
    ["not-a-port", 0, -1, 65536],
)
async def test_zeroconf_flow_aborts_invalid_port_payload(port: Any) -> None:
    """Reject discovery payloads that do not contain a usable TCP port."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        can_connect = AsyncMock(return_value=True)
        with patch.object(config_flow, "_can_connect", can_connect):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info("dhe-ja06.local.", port),
            )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "invalid_discovery_parameters"
        can_connect.assert_not_awaited()



@pytest.mark.usefixtures("flow_only")
async def test_user_flow_can_select_in_progress_zeroconf_discovery() -> None:
    """Run Add Device through the visible Zeroconf/scan/manual choice."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(
            return_value=config_flow.SetupPairingResult(
                unique_id="aa:bb:cc:dd:ee:ff",
            )
        )
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            zeroconf = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info("DHE-JA06.local.", DEFAULT_PORT),
            )
            assert zeroconf["type"] is FlowResultType.FORM
            assert zeroconf["step_id"] == "zeroconf_confirm"

            user = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )
            assert user["type"] is FlowResultType.FORM
            assert user["step_id"] == "user"
            defaults = _schema_defaults(user["data_schema"])
            assert (
                defaults[config_flow.CONF_SETUP_MODE]
                == config_flow.SETUP_MODE_SCAN
            )

            result = await hass.config_entries.flow.async_configure(
                user["flow_id"],
                user_input={
                    config_flow.CONF_SETUP_MODE: "zeroconf:192.0.2.124:8443",
                },
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "zeroconf_confirm"
            progress = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
            assert all(flow["flow_id"] != zeroconf["flow_id"] for flow in progress)
            assert any(flow["flow_id"] == result["flow_id"] for flow in progress)

            duplicate = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info("DHE-JA06.local.", DEFAULT_PORT),
            )
            assert duplicate["type"] is FlowResultType.ABORT
            assert duplicate["reason"] == "already_in_progress"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55"},
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "pairing_confirm"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={},
            )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "DHE-JA06"
        assert result["data"][CONF_HOST] == "192.0.2.124"
        assert result["result"].unique_id == "aa:bb:cc:dd:ee:ff"
        assert can_connect.await_count == 2
        validate_pairing.assert_awaited_once()



async def test_user_zeroconf_takeover_keeps_source_flow_on_connect_failure() -> None:
    """Keep the original discovery setup path when takeover cannot connect."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        can_connect = AsyncMock(side_effect=[True, False])
        with patch.object(config_flow, "_can_connect", can_connect):
            zeroconf = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info("DHE-JA06.local.", DEFAULT_PORT),
            )
            assert zeroconf["type"] is FlowResultType.FORM
            assert zeroconf["step_id"] == "zeroconf_confirm"

            user = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )
            result = await hass.config_entries.flow.async_configure(
                user["flow_id"],
                user_input={
                    config_flow.CONF_SETUP_MODE: "zeroconf:192.0.2.124:8443",
                },
            )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "cannot_connect"
        assert can_connect.await_count == 2
        progress = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        assert any(flow["flow_id"] == zeroconf["flow_id"] for flow in progress)



async def test_zeroconf_flow_aborts_duplicate_host_port() -> None:
    """Verify Zeroconf discovery does not start for an existing DHE target."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="192.0.2.124",
            port=DEFAULT_PORT,
            name="Existing DHE",
            unique_id="existing-fixture-dhe",
        )
        entry.add_to_hass(hass)

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=_zeroconf_info("DHE-JA06.local.", DEFAULT_PORT),
        )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"



async def test_zeroconf_flow_does_not_suppress_prompt_without_existing_entry() -> None:
    """Do not hide discovery prompts when no DHE config entry exists."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        can_connect = AsyncMock(return_value=True)
        recent_prompt_seen = AsyncMock(return_value=True)
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(
                config_flow,
                "_async_recent_discovery_prompt_seen",
                recent_prompt_seen,
            ),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info("DHE-JA06.local.", DEFAULT_PORT),
            )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "zeroconf_confirm"
        recent_prompt_seen.assert_not_awaited()
        can_connect.assert_awaited_once_with(hass, "192.0.2.124", DEFAULT_PORT)



async def test_zeroconf_updates_existing_entry_for_identity_matched_host_change() -> None:
    """Update host/port on an existing entry when Zeroconf identity matches."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="dhe-ja06.local",
            port=DEFAULT_PORT,
            name="Existing DHE",
            unique_id="aa:bb:cc:dd:ee:ff",
        )
        entry.add_to_hass(hass)

        can_connect = AsyncMock(return_value=True)
        preserve_token = AsyncMock()
        reload_entry = AsyncMock(return_value=True)
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(
                config_flow,
                "_async_preserve_token_for_retarget",
                preserve_token,
            ),
            patch.object(hass.config_entries, "async_reload", reload_entry),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info(
                    "dhe-ja06.local.",
                    9443,
                    host="192.0.2.124",
                    properties={"wlan_mac": "aa-bb-cc-dd-ee-ff"},
                ),
            )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"
        updated_entry = hass.config_entries.async_get_entry(entry.entry_id)
        assert updated_entry is not None
        assert updated_entry.data[CONF_HOST] == "192.0.2.124"
        assert updated_entry.data[CONF_PORT] == 9443
        assert updated_entry.unique_id == "aa:bb:cc:dd:ee:ff"
        assert len(hass.config_entries.async_entries(DOMAIN)) == 1
        can_connect.assert_awaited_once_with(hass, "192.0.2.124", 9443)
        preserve_token.assert_awaited_once()
        reload_entry.assert_awaited_once_with(entry.entry_id)



async def test_zeroconf_update_uses_update_listener_for_loaded_entry() -> None:
    """Avoid a direct reload when a loaded entry already reloads via update listener."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="dhe-ja06.local",
            port=DEFAULT_PORT,
            name="Existing DHE",
            unique_id="aa:bb:cc:dd:ee:ff",
        )
        entry.add_to_hass(hass)
        update_listener = AsyncMock()
        entry.add_update_listener(update_listener)

        can_connect = AsyncMock(return_value=True)
        preserve_token = AsyncMock()
        reload_entry = AsyncMock(return_value=True)
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(
                config_flow,
                "_async_preserve_token_for_retarget",
                preserve_token,
            ),
            patch.object(hass.config_entries, "async_reload", reload_entry),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info(
                    "dhe-ja06.local.",
                    9443,
                    host="192.0.2.124",
                    properties={"wlan_mac": "aa-bb-cc-dd-ee-ff"},
                ),
            )
            await hass.async_block_till_done()

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"
        updated_entry = hass.config_entries.async_get_entry(entry.entry_id)
        assert updated_entry is not None
        assert updated_entry.data[CONF_HOST] == "192.0.2.124"
        assert updated_entry.data[CONF_PORT] == 9443
        preserve_token.assert_awaited_once()
        update_listener.assert_awaited_once_with(hass, entry)
        reload_entry.assert_not_awaited()



async def test_zeroconf_identity_match_keeps_existing_target_when_update_unreachable() -> None:
    """Do not retarget an existing entry to an unreachable discovery endpoint."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="dhe-ja06.local",
            port=DEFAULT_PORT,
            name="Existing DHE",
            unique_id="aa:bb:cc:dd:ee:ff",
        )
        entry.add_to_hass(hass)

        can_connect = AsyncMock(return_value=False)
        preserve_token = AsyncMock()
        reload_entry = AsyncMock(return_value=True)
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(
                config_flow,
                "_async_preserve_token_for_retarget",
                preserve_token,
            ),
            patch.object(hass.config_entries, "async_reload", reload_entry),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info(
                    "dhe-ja06.local.",
                    9443,
                    host="192.0.2.124",
                    properties={"wlan_mac": "aa-bb-cc-dd-ee-ff"},
                ),
            )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "cannot_connect"
        updated_entry = hass.config_entries.async_get_entry(entry.entry_id)
        assert updated_entry is not None
        assert updated_entry.data[CONF_HOST] == "dhe-ja06.local"
        assert updated_entry.data[CONF_PORT] == DEFAULT_PORT
        assert updated_entry.unique_id == "aa:bb:cc:dd:ee:ff"
        assert len(hass.config_entries.async_entries(DOMAIN)) == 1
        can_connect.assert_awaited_once_with(hass, "192.0.2.124", 9443)
        preserve_token.assert_not_awaited()
        reload_entry.assert_not_awaited()



async def test_zeroconf_identity_match_aborts_on_target_conflict_without_update() -> None:
    """Abort with conflict when identity matches one entry but target belongs to another."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        matched_entry = _build_mock_entry(
            host="dhe-ja06.local",
            port=DEFAULT_PORT,
            name="Matched DHE",
            unique_id="aa:bb:cc:dd:ee:ff",
        )
        target_entry = _build_mock_entry(
            host="192.0.2.150",
            port=DEFAULT_PORT,
            name="Other DHE",
            unique_id="11:22:33:44:55:66",
        )
        matched_entry.add_to_hass(hass)
        target_entry.add_to_hass(hass)

        issue_registry = ir.async_get(hass)
        issue_id = config_flow._discovery_conflict_issue_id("192.0.2.150", DEFAULT_PORT)

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=_zeroconf_info(
                "dhe-ja06.local.",
                DEFAULT_PORT,
                host="192.0.2.150",
                properties={"wlan_mac": "aa-bb-cc-dd-ee-ff"},
            ),
        )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "conflicting_discovery_identity"
        assert len(hass.config_entries.async_entries(DOMAIN)) == 2
        assert matched_entry.data[CONF_HOST] == "dhe-ja06.local"
        issue = issue_registry.async_get_issue(DOMAIN, issue_id)
        assert issue is not None
        assert issue.translation_key == "discovery_conflict"



async def test_zeroconf_pairing_aborts_duplicate_mac_after_host_ip_mismatch() -> None:
    """Abort when Zeroconf finds an existing manual entry through another host."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="dhe-ja06.local",
            port=DEFAULT_PORT,
            name="Existing DHE",
            unique_id="aa:bb:cc:dd:ee:ff",
        )
        entry.add_to_hass(hass)

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(
            return_value=config_flow.SetupPairingResult(
                unique_id="aa:bb:cc:dd:ee:ff",
            )
        )
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info(
                    "dhe-ja06.local.",
                    DEFAULT_PORT,
                    host="192.0.2.124",
                ),
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "zeroconf_confirm"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55"},
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "pairing_confirm"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={},
            )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"
        assert len(hass.config_entries.async_entries(DOMAIN)) == 1
        can_connect.assert_awaited_once_with(hass, "192.0.2.124", DEFAULT_PORT)
        validate_pairing.assert_awaited_once()



async def test_zeroconf_flow_aborts_matching_flow_already_in_progress() -> None:
    """Verify duplicate Zeroconf discoveries share one setup flow."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        with patch.object(config_flow, "_can_connect", AsyncMock(return_value=True)):
            first = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info("DHE-JA06.local.", DEFAULT_PORT),
            )
            second = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info("dhe-ja06.local", DEFAULT_PORT),
            )

        assert first["type"] is FlowResultType.FORM
        assert first["step_id"] == "zeroconf_confirm"
        assert second["type"] is FlowResultType.ABORT
        assert second["reason"] == "already_in_progress"
