"""Real Home Assistant integration regression tests."""

from __future__ import annotations

import asyncio
import importlib
import types
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries, loader
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers import (
    issue_registry as ir,
)

from tests.ha_test_support import (
    DEFAULT_PORT,
    DOMAIN,
    STORED_TOKEN,
    FakeDHEEngineIOServer,
    _async_test_home_assistant,
    _build_mock_entry,
    _clear_loaded_integration_modules,
    _ensure_network_loaded,
    _entity_id_for_key,
    _FixtureDHEClient,
    _isolate_discovery_cache,  # noqa: F401 - registers the pytest fixture
    _zeroconf_info,
)

pytestmark = pytest.mark.asyncio


async def test_repairs_belong_to_entry_and_are_deleted_with_it() -> None:
    """HA removes only the deleted entry's issues, including unloaded entries."""
    _clear_loaded_integration_modules()
    repairs = importlib.import_module(f"custom_components.{DOMAIN}.repair_issues")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entries = [
            _build_mock_entry(host="127.0.0.1", port=DEFAULT_PORT, name=name, unique_id=name)
            for name in ("repair-owner-a", "repair-owner-b")
        ]
        for entry in entries:
            entry.add_to_hass(hass)
            for issue_type in repairs.ALL_REPAIR_ISSUES:
                repairs.async_create_repair_issue(hass, entry.entry_id, issue_type, entry.title)
                issue = ir.async_get(hass).async_get_issue(
                    DOMAIN, repairs.repair_issue_id(issue_type, entry.entry_id)
                )
                assert issue is not None
                if repairs.HA_2026_11:
                    assert issue.config_entry_id == entry.entry_id
                assert issue.data["entry_id"] == entry.entry_id

        await hass.config_entries.async_remove(entries[0].entry_id)
        await hass.async_block_till_done()
        for issue_type in repairs.ALL_REPAIR_ISSUES:
            assert ir.async_get(hass).async_get_issue(
                DOMAIN, repairs.repair_issue_id(issue_type, entries[0].entry_id)
            ) is None
            assert ir.async_get(hass).async_get_issue(
                DOMAIN, repairs.repair_issue_id(issue_type, entries[1].entry_id)
            ) is not None
        repairs.async_create_pairing_issue(hass, entries[0].entry_id, "Removed entry")
        assert ir.async_get(hass).async_get_issue(
            DOMAIN, repairs.pairing_required_issue_id(entries[0].entry_id)
        ) is None



async def test_runtime_auth_failure_creates_single_repair_issue() -> None:
    """Runtime auth failures create one DHE repair issue without generic reauth."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Auth Failure Fixture DHE",
            unique_id="auth-failure-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        with patch.object(entry, "async_start_reauth") as start_reauth:
            client.emit_diagnostic({"connection_state": "auth_failed"})
            client.emit_diagnostic({"auth_failure": True})
            await hass.async_block_till_done()

        start_reauth.assert_not_called()
        issue_id = repair_issues.pairing_required_issue_id(entry.entry_id)
        reauth_issue_id = f"config_entry_reauth_{DOMAIN}_{entry.entry_id}"
        issue_registry = ir.async_get(hass)
        issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
        assert issue is not None
        assert issue.is_fixable
        assert issue.severity is ir.IssueSeverity.ERROR
        assert issue.translation_key == "pairing_required"
        assert issue.data == {
            "entry_id": entry.entry_id,
            "issue_type": "pairing_required",
        }
        assert issue_registry.async_get_issue("homeassistant", reauth_issue_id) is None
        assert not hass.config_entries.flow.async_progress_by_handler(
            DOMAIN,
            match_context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
        )

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()



async def test_runtime_auth_failure_does_not_create_duplicate_repair_issues() -> None:
    """Repeated auth-failure diagnostics should not spam duplicate Repairs."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="No Duplicate Repair Fixture DHE",
            unique_id="no-duplicate-repair-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        with patch.object(
            integration,
            "async_create_repair_issue",
            wraps=integration.async_create_repair_issue,
        ) as create_issue:
            client.emit_diagnostic({"connection_state": "auth_failed"})
            client.emit_diagnostic({"connection_state": "auth_failed"})
            client.emit_diagnostic({"auth_failure": True})
            await hass.async_block_till_done()

        assert create_issue.call_count == 1
        issue_id = repair_issues.pairing_required_issue_id(entry.entry_id)
        issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
        assert issue is not None

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()



async def test_runtime_auth_failure_with_token_reason_creates_token_invalid_issue() -> None:
    """Auth failures with token-specific reason map to token_invalid repairs."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Token Invalid Fixture DHE",
            unique_id="token-invalid-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        client.emit_diagnostic(
            {
                "connection_state": "auth_failed",
                "auth_failure": True,
                "last_reconnect_reason": (
                    "DHEAuthError: stored token is no longer accepted"
                ),
            }
        )
        await hass.async_block_till_done()

        issue_registry = ir.async_get(hass)
        token_issue_id = repair_issues.token_invalid_issue_id(entry.entry_id)
        pairing_issue_id = repair_issues.pairing_required_issue_id(entry.entry_id)
        token_issue = issue_registry.async_get_issue(DOMAIN, token_issue_id)
        assert token_issue is not None
        assert token_issue.translation_key == "token_invalid"
        assert issue_registry.async_get_issue(DOMAIN, pairing_issue_id) is None

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()



async def test_runtime_connectivity_repairs_respect_grace_and_classify_target() -> None:
    """Do not raise connectivity repairs inside grace; classify host/target hints."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Connectivity Repair Fixture DHE",
            unique_id="connectivity-repair-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        issue_registry = ir.async_get(hass)
        device_issue_id = repair_issues.device_unreachable_issue_id(entry.entry_id)
        host_issue_id = repair_issues.host_changed_or_unreachable_issue_id(
            entry.entry_id
        )
        token_issue_id = repair_issues.token_invalid_issue_id(entry.entry_id)

        client.emit_diagnostic(
            {
                "connection_state": "reconnecting",
                "should_mark_unavailable": False,
                "last_reconnect_reason": "ServerDisconnectedError: socket closed",
            }
        )
        await hass.async_block_till_done()
        assert issue_registry.async_get_issue(DOMAIN, device_issue_id) is None
        assert issue_registry.async_get_issue(DOMAIN, host_issue_id) is None

        client.emit_diagnostic(
            {
                "connection_state": "reconnecting",
                "should_mark_unavailable": True,
                "last_reconnect_reason": "ServerDisconnectedError: socket closed",
            }
        )
        await hass.async_block_till_done()
        assert issue_registry.async_get_issue(DOMAIN, device_issue_id) is not None
        assert issue_registry.async_get_issue(DOMAIN, host_issue_id) is None

        client.emit_diagnostic(
            {
                "connection_state": "reconnecting",
                "should_mark_unavailable": True,
                "last_reconnect_reason": (
                    "ClientConnectorError: name or service not known"
                ),
            }
        )
        await hass.async_block_till_done()
        assert issue_registry.async_get_issue(DOMAIN, host_issue_id) is not None
        assert issue_registry.async_get_issue(DOMAIN, device_issue_id) is None
        assert issue_registry.async_get_issue(DOMAIN, token_issue_id) is None

        client.emit_diagnostic(
            {
                "connection_state": "reconnecting",
                "should_mark_unavailable": True,
                "last_reconnect_reason": (
                    'DHEError: GET 400: {"code":400,"message":"Session ID unknown"}'
                ),
            }
        )
        await hass.async_block_till_done()
        assert issue_registry.async_get_issue(DOMAIN, token_issue_id) is not None
        assert issue_registry.async_get_issue(DOMAIN, host_issue_id) is None
        assert issue_registry.async_get_issue(DOMAIN, device_issue_id) is None

        client.emit_diagnostic({"connection_state": "initializing"})
        await hass.async_block_till_done()
        assert issue_registry.async_get_issue(DOMAIN, host_issue_id) is None
        assert issue_registry.async_get_issue(DOMAIN, token_issue_id) is not None

        client.emit_diagnostic({"connection_state": "connected"})
        await hass.async_block_till_done()
        assert issue_registry.async_get_issue(DOMAIN, token_issue_id) is None

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()



async def test_runtime_discovery_conflict_repair_issue_lifecycle() -> None:
    """Discovery-conflict repair issue is created and cleared on recovery."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Discovery Conflict Fixture DHE",
            unique_id="discovery-conflict-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        issue_id = repair_issues.discovery_conflict_issue_id(entry.entry_id)
        issue_registry = ir.async_get(hass)
        client.emit_diagnostic(
            {
                "connection_state": "reconnecting",
                "discovery_conflict": True,
            }
        )
        await hass.async_block_till_done()
        issue = issue_registry.async_get_issue(DOMAIN, issue_id)
        assert issue is not None
        assert issue.translation_key == "discovery_conflict"

        client.emit_diagnostic({"connection_state": "connected"})
        await hass.async_block_till_done()
        assert issue_registry.async_get_issue(DOMAIN, issue_id) is None

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()



async def test_runtime_stored_token_pairing_prompt_creates_single_repair_issue() -> None:
    """A deleted DHE token must become one HA repair, not a silent pairing prompt."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    protocol = importlib.import_module(f"custom_components.{DOMAIN}.protocol")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    token_file_helpers = importlib.import_module(
        f"custom_components.{DOMAIN}.token_file_helpers"
    )
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        await _ensure_network_loaded(hass)
        async with FakeDHEEngineIOServer(protocol.NS) as server:
            token_file = Path(
                hass.config.path(
                    token_file_helpers.token_file_for_target(
                        server.host,
                        server.port,
                    )
                )
            )
            token_file.parent.mkdir(parents=True, exist_ok=True)
            token_file.write_text(STORED_TOKEN, encoding="utf-8")
            server.queue_pairing_request()

            entry = _build_mock_entry(
                host=server.host,
                port=server.port,
                name="Stored Token Deleted Fixture DHE",
                unique_id="stored-token-deleted-fixture-dhe",
            )
            entry.add_to_hass(hass)
            with patch.object(
                integration,
                "_async_can_connect",
                AsyncMock(return_value=True),
            ):
                assert await hass.config_entries.async_setup(entry.entry_id)

            pairing_issue_id = repair_issues.pairing_required_issue_id(entry.entry_id)
            token_issue_id = repair_issues.token_invalid_issue_id(entry.entry_id)
            reauth_issue_id = f"config_entry_reauth_{DOMAIN}_{entry.entry_id}"
            issue_registry = ir.async_get(hass)
            issue = None
            for _attempt in range(40):
                await hass.async_block_till_done()
                issue = issue_registry.async_get_issue(
                    DOMAIN, token_issue_id
                ) or issue_registry.async_get_issue(DOMAIN, pairing_issue_id)
                if issue is not None:
                    break
                await asyncio.sleep(0.05)

            assert issue is not None
            assert issue.translation_key in {"token_invalid", "pairing_required"}
            assert issue_registry.async_get_issue("homeassistant", reauth_issue_id) is None
            assert not hass.config_entries.flow.async_progress_by_handler(
                DOMAIN,
                match_context={
                    "source": config_entries.SOURCE_REAUTH,
                    "entry_id": entry.entry_id,
                },
            )
            assert entry.data["token"] == STORED_TOKEN
            assert token_file.exists()
            assert entry.data["legacy_token_files"] == [token_file.name]

            assert await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()



async def test_runtime_connected_deletes_stale_reauth_issues() -> None:
    """Successful runtime recovery clears stale DHE and HA reauth issues."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Recovered Fixture DHE",
            unique_id="recovered-fixture-dhe",
        )
        entry.add_to_hass(hass)
        issue_id = repair_issues.pairing_required_issue_id(entry.entry_id)
        reauth_issue_id = f"config_entry_reauth_{DOMAIN}_{entry.entry_id}"
        issue_registry = ir.async_get(hass)
        repair_issues.async_create_pairing_issue(hass, entry.entry_id, entry.title)
        ir.async_create_issue(
            hass,
            "homeassistant",
            reauth_issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="config_entry_reauth",
        )
        assert issue_registry.async_get_issue(DOMAIN, issue_id) is not None
        assert issue_registry.async_get_issue("homeassistant", reauth_issue_id) is not None

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        assert issue_registry.async_get_issue(DOMAIN, issue_id) is None
        assert issue_registry.async_get_issue("homeassistant", reauth_issue_id) is None

        repair_issues.async_create_pairing_issue(hass, entry.entry_id, entry.title)
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
                "title_placeholders": {"name": entry.title},
                "unique_id": entry.unique_id,
            },
            data=dict(entry.data),
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"
        ir.async_create_issue(
            hass,
            "homeassistant",
            reauth_issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="config_entry_reauth",
        )
        entity_registry = er.async_get(hass)
        saving_entity = next(
            entity
            for entity in er.async_entries_for_config_entry(
                entity_registry,
                entry.entry_id,
            )
            if entity.translation_key == "odb_possible_energy_saving"
        )
        statistic_issue_id = f"mean_type_changed_{saving_entity.entity_id}"
        ir.async_create_issue(
            hass,
            "sensor",
            statistic_issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="mean_type_changed",
        )
        assert issue_registry.async_get_issue(DOMAIN, issue_id) is not None
        assert issue_registry.async_get_issue("homeassistant", reauth_issue_id) is not None
        assert issue_registry.async_get_issue("sensor", statistic_issue_id) is not None
        assert hass.config_entries.flow.async_progress_by_handler(
            DOMAIN,
            match_context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
        )

        client.emit_diagnostic({"connection_state": "initializing"})
        assert issue_registry.async_get_issue(DOMAIN, issue_id) is not None
        assert issue_registry.async_get_issue("homeassistant", reauth_issue_id) is not None
        assert issue_registry.async_get_issue("sensor", statistic_issue_id) is not None
        client.emit_diagnostic({"connection_state": "connected"})
        await hass.async_block_till_done()

        assert issue_registry.async_get_issue(DOMAIN, issue_id) is None
        assert issue_registry.async_get_issue("homeassistant", reauth_issue_id) is None
        assert issue_registry.async_get_issue("sensor", statistic_issue_id) is None
        assert not hass.config_entries.flow.async_progress_by_handler(
            DOMAIN,
            match_context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
        )

        repair_issues.async_create_pairing_issue(hass, entry.entry_id, entry.title)
        assert issue_registry.async_get_issue(DOMAIN, issue_id) is None
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key="pairing_required",
            data={"entry_id": entry.entry_id},
        )
        assert issue_registry.async_get_issue(DOMAIN, issue_id) is not None
        client.emit_diagnostic({"connection_state": "connected"})
        await hass.async_block_till_done()
        assert issue_registry.async_get_issue(DOMAIN, issue_id) is None

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()



async def test_connected_diagnostics_schedule_one_cleanup_task_per_connected_phase() -> None:
    """Repeated connected diagnostics must not create unbounded cleanup tasks."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Connected Task Guard DHE",
            unique_id="connected-task-guard-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
            patch.object(integration, "_async_schedule_connected_issue_cleanup") as schedule_cleanup,
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

            schedule_cleanup.reset_mock()
            client.emit_diagnostic(
                {"connection_state": "connected", "message_count": 1}
            )
            client.emit_diagnostic(
                {"connection_state": "connected", "message_count": 2}
            )
            client.emit_diagnostic(
                {"connection_state": "connected", "message_count": 3}
            )
            await hass.async_block_till_done()

            assert schedule_cleanup.call_count == 1

            client.emit_diagnostic(
                {
                    "connection_state": "reconnecting",
                    "last_reconnect_reason": "ServerDisconnectedError: socket closed",
                }
            )
            client.emit_diagnostic(
                {"connection_state": "connected", "message_count": 4}
            )
            await hass.async_block_till_done()

            assert schedule_cleanup.call_count == 2

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()



async def test_auth_failure_diagnostics_schedule_one_reauth_clear_task_per_phase() -> None:
    """Repeated auth-failure diagnostics must not create unbounded cleanup tasks."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Auth Task Guard DHE",
            unique_id="auth-task-guard-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
            patch.object(integration, "_async_schedule_config_entry_reauth_clear") as schedule_reauth_clear,
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

            schedule_reauth_clear.reset_mock()
            client.emit_diagnostic({"connection_state": "auth_failed"})
            client.emit_diagnostic(
                {"connection_state": "auth_failed", "auth_failure": True}
            )
            client.emit_diagnostic(
                {
                    "connection_state": "auth_failed",
                    "auth_failure": True,
                    "message_count": 1,
                }
            )
            await hass.async_block_till_done()

            assert schedule_reauth_clear.call_count == 1

            client.emit_diagnostic({"connection_state": "initializing"})
            client.emit_diagnostic(
                {"connection_state": "auth_failed", "auth_failure": True}
            )
            await hass.async_block_till_done()

            assert schedule_reauth_clear.call_count == 2

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()



async def test_cleanup_schedulers_reuse_runtime_task_slots() -> None:
    """Cleanup schedulers should not retain a new unload callback per task."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Runtime Task Slot DHE",
            unique_id="runtime-task-slot-fixture-dhe",
        )
        entry.add_to_hass(hass)
        runtime = integration.DHEConnectRuntimeData(client=client, name=entry.title)
        integration.set_runtime_data(entry, runtime)

        integration._async_schedule_connected_issue_cleanup(hass, entry, client)
        connected_cleanup_task = runtime.connected_cleanup_task
        assert connected_cleanup_task is not None
        integration._async_schedule_connected_issue_cleanup(hass, entry, client)
        assert runtime.connected_cleanup_task is connected_cleanup_task

        integration._async_schedule_config_entry_reauth_clear(hass, entry)
        reauth_clear_task = runtime.reauth_clear_task
        assert reauth_clear_task is not None
        integration._async_schedule_config_entry_reauth_clear(hass, entry)
        assert runtime.reauth_clear_task is reauth_clear_task

        await integration.cancel_task_if_pending(connected_cleanup_task)
        await integration.cancel_task_if_pending(reauth_clear_task)



async def test_repairs_flow_keeps_issue_when_dhe_is_unreachable() -> None:
    """Keep a Repairs issue open when the DHE cannot be reached."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    repairs = importlib.import_module(f"custom_components.{DOMAIN}.repairs")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="repair-offline-dhe.local",
            port=DEFAULT_PORT,
            name="Repair Offline Fixture DHE",
            unique_id="repair-offline-fixture-dhe",
        )
        entry.add_to_hass(hass)
        repair_issues.async_create_pairing_issue(hass, entry.entry_id, entry.title)
        issue_id = repair_issues.pairing_required_issue_id(entry.entry_id)
        issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
        assert issue is not None

        can_connect = AsyncMock(return_value=False)
        validate_pairing = AsyncMock(return_value=config_flow.SetupPairingResult())
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            repair_flow = await repairs.async_create_fix_flow(
                hass,
                issue_id,
                issue.data,
            )
            repair_flow.hass = hass
            repair_flow.handler = DOMAIN
            repair_flow.flow_id = "repair-offline-flow-id"
            repair_flow.context = {}
            repair_flow.init_data = {"issue_id": issue_id}

            result = await repair_flow.async_step_confirm({})

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "confirm"
        assert result["errors"]["base"] == "cannot_connect"
        can_connect.assert_awaited_once_with(
            hass,
            "repair-offline-dhe.local",
            DEFAULT_PORT,
        )
        validate_pairing.assert_not_awaited()
        assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None



async def test_repairs_flow_keeps_issue_when_pairing_validation_fails() -> None:
    """Surface pairing errors from a Repairs flow without closing the issue."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    repairs = importlib.import_module(f"custom_components.{DOMAIN}.repairs")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="repair-pairing-error-dhe.local",
            port=DEFAULT_PORT,
            name="Repair Pairing Error Fixture DHE",
            unique_id="repair-pairing-error-fixture-dhe",
        )
        entry.add_to_hass(hass)
        repair_issues.async_create_pairing_issue(hass, entry.entry_id, entry.title)
        issue_id = repair_issues.pairing_required_issue_id(entry.entry_id)
        issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
        assert issue is not None

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(
            return_value=config_flow.SetupPairingResult(error_key="pairing_timeout")
        )
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            repair_flow = await repairs.async_create_fix_flow(
                hass,
                issue_id,
                issue.data,
            )
            repair_flow.hass = hass
            repair_flow.handler = DOMAIN
            repair_flow.flow_id = "repair-pairing-error-flow-id"
            repair_flow.context = {}
            repair_flow.init_data = {"issue_id": issue_id}

            result = await repair_flow.async_step_confirm({})

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "confirm"
        assert result["errors"]["base"] == "pairing_timeout"
        can_connect.assert_awaited_once_with(
            hass,
            "repair-pairing-error-dhe.local",
            DEFAULT_PORT,
        )
        validate_pairing.assert_awaited_once()
        assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None



async def test_repairs_flow_aborts_when_issue_entry_is_missing() -> None:
    """Abort a stale Repairs issue whose config entry was removed."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    repairs = importlib.import_module(f"custom_components.{DOMAIN}.repairs")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with _async_test_home_assistant() as hass:
        missing_entry_id = "missing-repair-entry"
        issue_id = repair_issues.pairing_required_issue_id(missing_entry_id)
        repair_flow = await repairs.async_create_fix_flow(
            hass,
            issue_id,
            {"entry_id": missing_entry_id},
        )
        repair_flow.hass = hass
        repair_flow.handler = DOMAIN
        repair_flow.flow_id = "missing-repair-flow-id"
        repair_flow.context = {}
        repair_flow.init_data = {"issue_id": issue_id}

        result = await repair_flow.async_step_init()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "entry_not_found"



async def test_repairs_flow_rejects_mismatched_issue_data() -> None:
    """Reject Repairs issue IDs whose embedded entry ID does not match data."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    repairs = importlib.import_module(f"custom_components.{DOMAIN}.repairs")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with _async_test_home_assistant() as hass:
        issue_id = repair_issues.pairing_required_issue_id("entry-a")
        with pytest.raises(ValueError, match="does not match"):
            await repairs.async_create_fix_flow(
                hass,
                issue_id,
                {"entry_id": "entry-b"},
            )



async def test_repairs_flow_rejects_mismatched_issue_type_data() -> None:
    """Reject stale issue payloads that point to a different repair type."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    repairs = importlib.import_module(f"custom_components.{DOMAIN}.repairs")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with _async_test_home_assistant() as hass:
        issue_id = repair_issues.pairing_required_issue_id("entry-a")
        with pytest.raises(ValueError, match="type does not match"):
            await repairs.async_create_fix_flow(
                hass,
                issue_id,
                {"entry_id": "entry-a", "issue_type": repair_issues.TOKEN_INVALID_ISSUE},
            )



async def test_reauth_flow_repairs_pairing_with_real_hass_fixture() -> None:
    """Run HA reauth flow and verify it validates a fresh DHE pairing."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="reauth-dhe.local",
            port=DEFAULT_PORT,
            name="Reauth Fixture DHE",
            unique_id="reauth-fixture-dhe",
        )
        entry.add_to_hass(hass)
        restart_after_reauth = AsyncMock()
        entry.runtime_data = types.SimpleNamespace(
            client=types.SimpleNamespace(restart_after_reauth=restart_after_reauth),
            name=entry.title,
        )
        repair_issues.async_create_pairing_issue(hass, entry.entry_id, entry.title)
        issue_id = repair_issues.pairing_required_issue_id(entry.entry_id)
        assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(return_value=config_flow.SetupPairingResult())
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
            patch.object(hass.config_entries, "async_schedule_reload") as schedule_reload,
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_REAUTH,
                    "entry_id": entry.entry_id,
                },
                data=dict(entry.data),
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "reauth_confirm"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={},
            )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reauth_successful"
        can_connect.assert_awaited_once_with(hass, "reauth-dhe.local", DEFAULT_PORT)
        validate_pairing.assert_awaited_once()
        schedule_reload.assert_not_called()
        restart_after_reauth.assert_awaited_once_with()
        assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None



async def test_repairs_flow_validates_fresh_pairing_with_real_hass_fixture() -> None:
    """Run the fixable Repairs issue through the DHE pairing validation path."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    repairs = importlib.import_module(f"custom_components.{DOMAIN}.repairs")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="repair-flow-dhe.local",
            port=DEFAULT_PORT,
            name="Repair Flow Fixture DHE",
            unique_id="repair-flow-fixture-dhe",
        )
        entry.add_to_hass(hass)
        repair_issues.async_create_pairing_issue(hass, entry.entry_id, entry.title)
        issue_id = repair_issues.pairing_required_issue_id(entry.entry_id)
        issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
        assert issue is not None

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(return_value=config_flow.SetupPairingResult())
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            repair_flow = await repairs.async_create_fix_flow(
                hass,
                issue_id,
                issue.data,
            )
            repair_flow.hass = hass
            repair_flow.handler = DOMAIN
            repair_flow.flow_id = "repair-flow-id"
            repair_flow.context = {}
            repair_flow.init_data = {"issue_id": issue_id}

            result = await repair_flow.async_step_init()
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "confirm"

            result = await repair_flow.async_step_confirm({})

        assert result["type"] is FlowResultType.CREATE_ENTRY
        can_connect.assert_awaited_once_with(
            hass,
            "repair-flow-dhe.local",
            DEFAULT_PORT,
        )
        validate_pairing.assert_awaited_once()
        assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None



async def test_repairs_flow_aborts_when_entry_is_removed_before_confirm() -> None:
    """Abort repair confirm when the config entry disappears mid-flow."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    repairs = importlib.import_module(f"custom_components.{DOMAIN}.repairs")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with _async_test_home_assistant() as hass:
        entry = _build_mock_entry(
            host="repair-remove-dhe.local",
            port=DEFAULT_PORT,
            name="Repair Remove Fixture DHE",
            unique_id="repair-remove-fixture-dhe",
        )
        entry.add_to_hass(hass)
        repair_issues.async_create_pairing_issue(hass, entry.entry_id, entry.title)
        issue_id = repair_issues.pairing_required_issue_id(entry.entry_id)
        issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
        assert issue is not None

        repair_flow = await repairs.async_create_fix_flow(
            hass,
            issue_id,
            issue.data,
        )
        repair_flow.hass = hass
        repair_flow.handler = DOMAIN
        repair_flow.flow_id = "repair-missing-after-open"
        repair_flow.context = {}
        repair_flow.init_data = {"issue_id": issue_id}

        hass.config_entries._entries.pop(entry.entry_id, None)
        result = await repair_flow.async_step_confirm({})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "entry_not_found"



async def test_repairs_flow_success_reloads_existing_entry_without_duplication() -> None:
    """Successful repair reloads the same entry and keeps one device structure."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    repairs = importlib.import_module(f"custom_components.{DOMAIN}.repairs")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Repair Reload Fixture DHE",
            unique_id="repair-reload-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        entry_count_before = len(hass.config_entries.async_entries(DOMAIN))
        device_count_before = len(
            dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
        )

        repair_issues.async_create_pairing_issue(hass, entry.entry_id, entry.title)
        issue_id = repair_issues.pairing_required_issue_id(entry.entry_id)
        issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
        assert issue is not None

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(return_value=config_flow.SetupPairingResult())
        reload_entry = AsyncMock(return_value=True)
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
            patch.object(hass.config_entries, "async_reload", reload_entry),
        ):
            repair_flow = await repairs.async_create_fix_flow(
                hass,
                issue_id,
                issue.data,
            )
            repair_flow.hass = hass
            repair_flow.handler = DOMAIN
            repair_flow.flow_id = "repair-reload-flow-id"
            repair_flow.context = {}
            repair_flow.init_data = {"issue_id": issue_id}

            result = await repair_flow.async_step_confirm({})

        assert result["type"] is FlowResultType.CREATE_ENTRY
        can_connect.assert_awaited_once_with(hass, client.host, client.port)
        validate_pairing.assert_awaited_once()
        assert reload_entry.await_count >= 1
        assert all(
            call.args == (entry.entry_id,)
            for call in reload_entry.await_args_list
        )
        assert len(hass.config_entries.async_entries(DOMAIN)) == entry_count_before
        assert (
            len(dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id))
            == device_count_before
        )
        assert entry.unique_id == "repair-reload-fixture-dhe"
        assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()



async def test_token_invalid_repairs_flow_reuses_pairing_validation_path() -> None:
    """token_invalid issues must use the same pairing repair flow."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    repairs = importlib.import_module(f"custom_components.{DOMAIN}.repairs")
    repair_issues = importlib.import_module(
        f"custom_components.{DOMAIN}.repair_issues"
    )
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="token-flow-dhe.local",
            port=DEFAULT_PORT,
            name="Token Flow Fixture DHE",
            unique_id="token-flow-fixture-dhe",
        )
        entry.add_to_hass(hass)
        repair_issues.async_create_repair_issue(
            hass,
            entry.entry_id,
            repair_issues.TOKEN_INVALID_ISSUE,
            entry.title,
        )
        issue_id = repair_issues.token_invalid_issue_id(entry.entry_id)
        issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
        assert issue is not None

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(return_value=config_flow.SetupPairingResult())
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            repair_flow = await repairs.async_create_fix_flow(
                hass,
                issue_id,
                issue.data,
            )
            repair_flow.hass = hass
            repair_flow.handler = DOMAIN
            repair_flow.flow_id = "token-repair-flow-id"
            repair_flow.context = {}
            repair_flow.init_data = {"issue_id": issue_id}

            result = await repair_flow.async_step_init()
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "confirm"

            result = await repair_flow.async_step_confirm({})

        assert result["type"] is FlowResultType.CREATE_ENTRY
        can_connect.assert_awaited_once_with(
            hass,
            "token-flow-dhe.local",
            DEFAULT_PORT,
        )
        validate_pairing.assert_awaited_once()
        assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None



async def test_zeroconf_conflict_creates_and_clears_discovery_repair_issue() -> None:
    """A hard Zeroconf identity conflict should raise and later clear a repair issue."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        issue_registry = ir.async_get(hass)
        conflict_host = "192.0.2.140"
        issue_id = config_flow._discovery_conflict_issue_id(conflict_host, DEFAULT_PORT)

        first = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=_zeroconf_info(
                "dhe-ja06.local.",
                DEFAULT_PORT,
                host=conflict_host,
                ip="192.0.2.141",
                name="DHE Connect DHE-JA06._ste-dhe._tcp.local.",
            ),
        )
        assert first["type"] is FlowResultType.ABORT
        assert first["reason"] == "conflicting_discovery_identity"
        issue = issue_registry.async_get_issue(DOMAIN, issue_id)
        assert issue is not None
        assert issue.translation_key == "discovery_conflict"

        can_connect = AsyncMock(return_value=True)
        with patch.object(config_flow, "_can_connect", can_connect):
            second = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_ZEROCONF},
                data=_zeroconf_info(
                    "dhe-ja06.local.",
                    DEFAULT_PORT,
                    host=conflict_host,
                    ip=conflict_host,
                    name="DHE Connect DHE-JA06._ste-dhe._tcp.local.",
                ),
            )
        assert second["type"] is FlowResultType.FORM
        assert second["step_id"] == "zeroconf_confirm"
        assert issue_registry.async_get_issue(DOMAIN, issue_id) is None



async def test_repair_pairing_button_calls_client_when_enabled_with_real_hass_fixture() -> None:
    """Enable the disabled-by-default repair button and press it through HA."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        client.available = False
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Repair Fixture DHE",
            unique_id="repair-fixture-dhe",
        )
        entry.add_to_hass(hass)

        registry = er.async_get(hass)
        registry.async_get_or_create(
            "button",
            DOMAIN,
            f"{DOMAIN}_{entry.entry_id}_repair_pairing",
            suggested_object_id="repair_fixture_dhe_repair_pairing",
            disabled_by=None,
        )

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        repair_button = _entity_id_for_key(
            hass,
            entry.entry_id,
            "button",
            "repair_pairing",
        )
        state = hass.states.get(repair_button)
        assert state is not None
        assert state.state != "unavailable"

        client.emit_availability(False)
        await hass.async_block_till_done()
        state = hass.states.get(repair_button)
        assert state is not None
        assert state.state != "unavailable"

        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": repair_button},
            blocking=True,
        )
        assert client.repair_pairing_calls == 1

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()



async def test_unavailable_runtime_blocks_controls_except_repair_button() -> None:
    """Do not execute normal DHE controls while runtime availability is false."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    protocol = importlib.import_module(f"custom_components.{DOMAIN}.protocol")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        weather_location = {
            "Name": "Berlin",
            "Country": "Germany",
            "LocationId": "ID=1",
        }
        radio_station = {"Id": 1, "Name": "Radio Test", "Country": "Germany"}
        client.last_weather_state = {
            "location": weather_location,
            "favorites": [weather_location],
        }
        client.last_radio_state = {
            "play": False,
            "volume": 40,
            "station": radio_station,
            "favorites": [radio_station],
        }
        client.last_measurements.update(
            {
                protocol.ID_BATH_FILL_TARGET_VOLUME: 80,
                protocol.ID_BRUSH_TIMER_ACTIVATION: True,
                protocol.ID_ECO_MODE: False,
            }
        )
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Unavailable Control Fixture DHE",
            unique_id="unavailable-control-fixture-dhe",
        )
        entry.add_to_hass(hass)

        registry = er.async_get(hass)
        registry.async_get_or_create(
            "button",
            DOMAIN,
            f"{DOMAIN}_{entry.entry_id}_reset_brush_timer",
            suggested_object_id="unavailable_control_fixture_dhe_reset_brush_timer",
            disabled_by=None,
        )

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        entity_ids = {
            "button": _entity_id_for_key(
                hass,
                entry.entry_id,
                "button",
                "reset_brush_timer",
            ),
            "climate": _entity_id_for_key(hass, entry.entry_id, "climate", "setpoint"),
            "media_player": _entity_id_for_key(
                hass,
                entry.entry_id,
                "media_player",
                "radio",
            ),
            "number": _entity_id_for_key(
                hass,
                entry.entry_id,
                "number",
                "bath_fill_target_volume",
            ),
            "switch": _entity_id_for_key(hass, entry.entry_id, "switch", "eco_mode"),
            "wellness": _entity_id_for_key(
                hass,
                entry.entry_id,
                "switch",
                "wellness_winter_pick_me_up",
            ),
        }

        client.emit_availability(False)
        await hass.async_block_till_done()
        offline_states = {
            key: (state.state if (state := hass.states.get(entity_id)) else None)
            for key, entity_id in entity_ids.items()
        }
        states = [hass.states.get(entity_id) for entity_id in entity_ids.values()]
        assert all(
            state is not None and state.state == "unavailable" for state in states
        ), offline_states

        blocked_calls = (
            ("button", "press", {"entity_id": entity_ids["button"]}),
            (
                "climate",
                "set_temperature",
                {"entity_id": entity_ids["climate"], "temperature": 39},
            ),
            ("media_player", "media_play", {"entity_id": entity_ids["media_player"]}),
            (
                "number",
                "set_value",
                {"entity_id": entity_ids["number"], "value": 90},
            ),
            ("switch", "turn_on", {"entity_id": entity_ids["switch"]}),
            ("switch", "turn_on", {"entity_id": entity_ids["wellness"]}),
        )
        for domain, service, data in blocked_calls:
            try:
                await hass.services.async_call(domain, service, data, blocking=True)
            except HomeAssistantError as err:
                assert "DHE is unavailable" in str(err)

        assert client.reset_brush_timer_calls == 0
        assert client.temperature_calls == []
        assert client.radio_play_calls == []
        assert client.bath_fill_target_volume_calls == []
        assert client.eco_mode_calls == []
        assert client.wellness_program_calls == []

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
