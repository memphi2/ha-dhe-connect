"""Real Home Assistant integration regression tests."""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries, loader
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
)
from homeassistant.data_entry_flow import FlowResultType

from tests.ha_test_support import (
    DEFAULT_PORT,
    DOMAIN,
    _async_test_home_assistant,
    _build_mock_entry,
    _clear_loaded_integration_modules,
    _FixtureDHEClient,
    _isolate_discovery_cache,  # noqa: F401 - registers the pytest fixture
    _schema_defaults,
)

pytestmark = pytest.mark.asyncio


async def test_config_flow_creates_entry_after_pairing_with_real_hass_fixture() -> None:
    """Run setup flow through HA's config-flow manager until entry creation."""
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
            patch.object(
                config_flow,
                "_async_recent_discovery_prompt_seen",
                AsyncMock(return_value=False),
            ),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
                data={
                    CONF_HOST: "http://dhe-fixture.local/",
                    CONF_PORT: DEFAULT_PORT,
                    CONF_NAME: "Flow Fixture DHE",
                    config_flow.CONF_INTERNAL_SCALD_PROTECTION: "50",
                },
            )

            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "pairing_confirm"
            can_connect.assert_awaited_once_with(
                hass,
                "dhe-fixture.local",
                DEFAULT_PORT,
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={},
            )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "Flow Fixture DHE"
        assert result["data"] == {
            CONF_HOST: "dhe-fixture.local",
            CONF_PORT: DEFAULT_PORT,
            CONF_NAME: "Flow Fixture DHE",
            config_flow.CONF_INTERNAL_SCALD_PROTECTION: "50",
        }
        assert result["result"].unique_id == "aa:bb:cc:dd:ee:ff"
        validate_pairing.assert_awaited_once()
        pairing_args = validate_pairing.await_args.args
        assert pairing_args[:3] == (
            hass,
            "dhe-fixture.local",
            DEFAULT_PORT,
        )
        assert pairing_args[3].endswith("_dhe-fixture.local_8443.txt")



async def test_config_flow_aborts_duplicate_target_with_real_hass_fixture() -> None:
    """Verify HA config flow prevents duplicate normalized DHE targets."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="dhe-duplicate.local",
            port=DEFAULT_PORT,
            name="Existing Fixture DHE",
            unique_id="existing-fixture-dhe",
        )
        entry.add_to_hass(hass)

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_HOST: "http://dhe-duplicate.local/",
                CONF_PORT: DEFAULT_PORT,
                CONF_NAME: "Duplicate Fixture DHE",
                "internal_scald_protection": "50",
            },
        )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"



async def test_options_connection_flow_migrates_legacy_token_for_changed_target() -> None:
    """Retarget options without forcing a fresh DHE pairing."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="old-dhe.local",
            port=DEFAULT_PORT,
            name="Old Fixture DHE",
            unique_id="old-fixture-dhe",
        )
        entry.add_to_hass(hass)
        old_token_path = Path(
            hass.config.path(config_flow.token_file_for_target("old-dhe.local", DEFAULT_PORT))
        )
        new_token_path = Path(
            hass.config.path(config_flow.token_file_for_target("new-dhe.local", DEFAULT_PORT))
        )
        old_token_path.parent.mkdir(parents=True, exist_ok=True)
        old_token_path.write_text("existing-token-value-0001", encoding="utf-8")

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(return_value=config_flow.SetupPairingResult())
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            result = await hass.config_entries.options.async_init(entry.entry_id)
            assert result["type"] is FlowResultType.MENU

            result = await hass.config_entries.options.async_configure(
                result["flow_id"],
                user_input={"next_step_id": "connection"},
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "connection"

            result = await hass.config_entries.options.async_configure(
                result["flow_id"],
                user_input={
                    CONF_HOST: "new-dhe.local",
                    CONF_PORT: DEFAULT_PORT,
                    CONF_NAME: "New Fixture DHE",
                    config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55",
                },
            )
            can_connect.assert_awaited_once_with(
                hass,
                "new-dhe.local",
                DEFAULT_PORT,
            )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"] == {
            CONF_HOST: "new-dhe.local",
            CONF_PORT: DEFAULT_PORT,
            CONF_NAME: "New Fixture DHE",
            config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55",
        }
        assert entry.data["token"] == "existing-token-value-0001"
        assert not old_token_path.exists()
        assert not new_token_path.exists()
        validate_pairing.assert_not_awaited()



async def test_reconfigure_flow_updates_connection_without_new_entry_with_real_hass_fixture() -> None:
    """Run HA reconfigure flow and verify it updates options on the same entry."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="reconfigure-old.local",
            port=DEFAULT_PORT,
            name="Reconfigure Old DHE",
            unique_id="reconfigure-fixture-dhe",
        )
        entry.add_to_hass(hass)
        old_token_path = Path(
            hass.config.path(
                config_flow.token_file_for_target("reconfigure-old.local", DEFAULT_PORT)
            )
        )
        new_token_path = Path(
            hass.config.path(
                config_flow.token_file_for_target("reconfigure-new.local", DEFAULT_PORT)
            )
        )
        old_token_path.parent.mkdir(parents=True, exist_ok=True)
        old_token_path.write_text(
            "existing-reconfigure-token-0001",
            encoding="utf-8",
        )

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(return_value=config_flow.SetupPairingResult())
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_RECONFIGURE,
                    "entry_id": entry.entry_id,
                },
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "reconfigure"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={
                    CONF_HOST: "reconfigure-new.local",
                    CONF_PORT: DEFAULT_PORT,
                    CONF_NAME: "Reconfigure New DHE",
                    config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55",
                },
            )
            can_connect.assert_awaited_once_with(
                hass,
                "reconfigure-new.local",
                DEFAULT_PORT,
            )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert entry.unique_id == "reconfigure-fixture-dhe"
        assert entry.options[CONF_HOST] == "reconfigure-new.local"
        assert entry.options[CONF_PORT] == DEFAULT_PORT
        assert entry.options[CONF_NAME] == "Reconfigure New DHE"
        assert entry.options[config_flow.CONF_INTERNAL_SCALD_PROTECTION] == "55"
        assert entry.data["token"] == "existing-reconfigure-token-0001"
        assert not old_token_path.exists()
        assert not new_token_path.exists()
        validate_pairing.assert_not_awaited()



async def test_reconfigure_flow_reloads_existing_loaded_entry() -> None:
    """Reconfigure should reload the existing loaded entry, not create a new one."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Reconfigure Reload Fixture DHE",
            unique_id="reconfigure-reload-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        reload_entry = AsyncMock(return_value=True)
        with patch.object(hass.config_entries, "async_reload", reload_entry):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_RECONFIGURE,
                    "entry_id": entry.entry_id,
                },
            )
            assert result["type"] is FlowResultType.FORM

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={
                    CONF_HOST: client.host,
                    CONF_PORT: client.port,
                    CONF_NAME: "Reconfigure Reload Updated DHE",
                    config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55",
                },
            )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert reload_entry.await_count >= 1
        assert all(
            call.args == (entry.entry_id,)
            for call in reload_entry.await_args_list
        )
        assert len(hass.config_entries.async_entries(DOMAIN)) == 1
        assert entry.unique_id == "reconfigure-reload-fixture-dhe"

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()



async def test_reconfigure_name_only_during_reconnect_grace_keeps_entry_identity() -> None:
    """Reconfigure must stay entry-local while the runtime is reconnecting."""
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(
            host=client.host,
            port=client.port,
            name="Reconnect Grace DHE",
            unique_id="reconfigure-reconnect-grace-fixture-dhe",
        )
        entry.add_to_hass(hass)

        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        client.emit_availability(True)
        client.emit_diagnostic(
            {
                "connection_state": "reconnecting",
                "should_mark_unavailable": False,
                "last_reconnect_reason": "ServerDisconnectedError: socket closed",
            }
        )
        await hass.async_block_till_done()

        can_connect = AsyncMock(return_value=True)
        reload_entry = AsyncMock(return_value=True)
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(hass.config_entries, "async_reload", reload_entry),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_RECONFIGURE,
                    "entry_id": entry.entry_id,
                },
            )
            assert result["type"] is FlowResultType.FORM

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={
                    CONF_HOST: client.host,
                    CONF_PORT: client.port,
                    CONF_NAME: "Reconnect Grace Renamed DHE",
                    config_flow.CONF_INTERNAL_SCALD_PROTECTION: "60",
                },
            )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert entry.unique_id == "reconfigure-reconnect-grace-fixture-dhe"
        assert entry.options[CONF_NAME] == "Reconnect Grace Renamed DHE"
        assert len(hass.config_entries.async_entries(DOMAIN)) == 1
        can_connect.assert_not_awaited()
        assert reload_entry.await_count >= 1
        assert all(
            call.args == (entry.entry_id,)
            for call in reload_entry.await_args_list
        )

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()



async def test_reconfigure_flow_updates_name_only_without_connectivity_check() -> None:
    """Changing only the display name must not trigger host/port checks."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="reconfigure-name-only.local",
            port=DEFAULT_PORT,
            name="Reconfigure Name Only DHE",
            unique_id="reconfigure-name-only-fixture-dhe",
        )
        entry.add_to_hass(hass)

        can_connect = AsyncMock(return_value=False)
        with patch.object(config_flow, "_can_connect", can_connect):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_RECONFIGURE,
                    "entry_id": entry.entry_id,
                },
            )
            assert result["type"] is FlowResultType.FORM

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={
                    CONF_HOST: "reconfigure-name-only.local",
                    CONF_PORT: DEFAULT_PORT,
                    CONF_NAME: "Reconfigure Name Updated DHE",
                    config_flow.CONF_INTERNAL_SCALD_PROTECTION: "50",
                },
            )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert entry.options[CONF_NAME] == "Reconfigure Name Updated DHE"
        can_connect.assert_not_awaited()



async def test_reconfigure_flow_updates_tmax_only_without_connectivity_check() -> None:
    """Changing only Tmax must not trigger host/port checks."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="reconfigure-tmax-only.local",
            port=DEFAULT_PORT,
            name="Reconfigure Tmax Only DHE",
            unique_id="reconfigure-tmax-only-fixture-dhe",
        )
        entry.add_to_hass(hass)

        can_connect = AsyncMock(return_value=False)
        with patch.object(config_flow, "_can_connect", can_connect):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_RECONFIGURE,
                    "entry_id": entry.entry_id,
                },
            )
            assert result["type"] is FlowResultType.FORM

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={
                    CONF_HOST: "reconfigure-tmax-only.local",
                    CONF_PORT: DEFAULT_PORT,
                    CONF_NAME: "Reconfigure Tmax Only DHE",
                    config_flow.CONF_INTERNAL_SCALD_PROTECTION: "60",
                },
            )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert entry.options[config_flow.CONF_INTERNAL_SCALD_PROTECTION] == "60"
        can_connect.assert_not_awaited()



async def test_reconfigure_flow_skips_pairing_for_unchanged_target_with_real_hass_fixture() -> None:
    """Keep reconfigure lightweight when host and port are unchanged."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="reconfigure-same.local",
            port=DEFAULT_PORT,
            name="Reconfigure Same DHE",
            unique_id="reconfigure-same-fixture-dhe",
        )
        entry.add_to_hass(hass)

        can_connect = AsyncMock(return_value=False)
        validate_pairing = AsyncMock(return_value=config_flow.SetupPairingResult())
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_RECONFIGURE,
                    "entry_id": entry.entry_id,
                },
            )
            assert result["type"] is FlowResultType.FORM

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={
                    CONF_HOST: "reconfigure-same.local",
                    CONF_PORT: DEFAULT_PORT,
                    CONF_NAME: "Renamed Same DHE",
                    config_flow.CONF_INTERNAL_SCALD_PROTECTION: "60",
                },
            )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert entry.options[CONF_NAME] == "Renamed Same DHE"
        assert entry.options[config_flow.CONF_INTERNAL_SCALD_PROTECTION] == "60"
        can_connect.assert_not_awaited()
        validate_pairing.assert_not_awaited()



async def test_reconfigure_flow_keeps_entered_values_when_new_target_is_unreachable() -> None:
    """Show reconfigure errors against the newly entered target, not old data."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="reconfigure-current.local",
            port=DEFAULT_PORT,
            name="Reconfigure Current DHE",
            unique_id="reconfigure-current-fixture-dhe",
        )
        entry.add_to_hass(hass)

        can_connect = AsyncMock(return_value=False)
        validate_pairing = AsyncMock(return_value=config_flow.SetupPairingResult())
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_RECONFIGURE,
                    "entry_id": entry.entry_id,
                },
            )
            assert result["type"] is FlowResultType.FORM

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={
                    CONF_HOST: "reconfigure-unreachable.local",
                    CONF_PORT: DEFAULT_PORT + 1,
                    CONF_NAME: "Unreachable Reconfigure DHE",
                    config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55",
                },
            )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reconfigure"
        assert result["errors"]["base"] == "cannot_connect"
        defaults = _schema_defaults(result["data_schema"])
        assert defaults[CONF_HOST] == "reconfigure-unreachable.local"
        assert defaults[CONF_PORT] == DEFAULT_PORT + 1
        assert defaults[CONF_NAME] == "Unreachable Reconfigure DHE"
        can_connect.assert_awaited_once_with(
            hass,
            "reconfigure-unreachable.local",
            DEFAULT_PORT + 1,
        )
        validate_pairing.assert_not_awaited()
        assert entry.options == {}



async def test_reconfigure_flow_changes_target_without_existing_token() -> None:
    """Allow target changes even when there is no legacy token file to migrate."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        entry = _build_mock_entry(
            host="reconfigure-retry-old.local",
            port=DEFAULT_PORT,
            name="Reconfigure Retry Old DHE",
            unique_id="reconfigure-retry-fixture-dhe",
        )
        entry.add_to_hass(hass)

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(return_value=config_flow.SetupPairingResult())
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_RECONFIGURE,
                    "entry_id": entry.entry_id,
                },
            )
            assert result["type"] is FlowResultType.FORM

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={
                    CONF_HOST: "reconfigure-retry-new.local",
                    CONF_PORT: DEFAULT_PORT,
                    CONF_NAME: "Reconfigure Retry New DHE",
                    config_flow.CONF_INTERNAL_SCALD_PROTECTION: "50",
                },
            )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert entry.options[CONF_HOST] == "reconfigure-retry-new.local"
        assert entry.options[CONF_NAME] == "Reconfigure Retry New DHE"
        can_connect.assert_awaited_once_with(
            hass,
            "reconfigure-retry-new.local",
            DEFAULT_PORT,
        )
        validate_pairing.assert_not_awaited()



async def test_reconfigure_flow_rejects_target_used_by_another_entry() -> None:
    """Prevent reconfigure from moving one DHE entry onto another target."""
    _clear_loaded_integration_modules()
    importlib.import_module(f"custom_components.{DOMAIN}")
    config_flow = importlib.import_module(f"custom_components.{DOMAIN}.config_flow")
    async with _async_test_home_assistant() as hass:
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        existing = _build_mock_entry(
            host="already-used-dhe.local",
            port=DEFAULT_PORT,
            name="Already Used DHE",
            unique_id="already-used-fixture-dhe",
        )
        existing.add_to_hass(hass)
        entry = _build_mock_entry(
            host="reconfigure-duplicate-old.local",
            port=DEFAULT_PORT,
            name="Reconfigure Duplicate Old DHE",
            unique_id="reconfigure-duplicate-fixture-dhe",
        )
        entry.add_to_hass(hass)

        can_connect = AsyncMock(return_value=True)
        validate_pairing = AsyncMock(return_value=config_flow.SetupPairingResult())
        with (
            patch.object(config_flow, "_can_connect", can_connect),
            patch.object(config_flow, "_validate_setup_pairing", validate_pairing),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_RECONFIGURE,
                    "entry_id": entry.entry_id,
                },
            )
            assert result["type"] is FlowResultType.FORM

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={
                    CONF_HOST: "already-used-dhe.local",
                    CONF_PORT: DEFAULT_PORT,
                    CONF_NAME: "Duplicate Target DHE",
                    config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55",
                },
            )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reconfigure"
        assert result["errors"]["base"] == "already_configured"
        defaults = _schema_defaults(result["data_schema"])
        assert defaults[CONF_HOST] == "reconfigure-duplicate-old.local"
        can_connect.assert_not_awaited()
        validate_pairing.assert_not_awaited()
        assert entry.options == {}
