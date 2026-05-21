"""Tests for config flow device settings defaults."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from ipaddress import ip_network
import sys
import types
from pathlib import Path
import unittest
from unittest.mock import AsyncMock


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FLOW_PATH = (
    ROOT / "custom_components" / "stiebel_dhe_connect" / "config_flow.py"
)
PACKAGE_ROOT = ROOT / "custom_components"
MODULE_NAME = "custom_components.stiebel_dhe_connect.config_flow"
_MISSING = object()
_RESTORED_MODULE_PREFIXES = (
    "homeassistant",
    "custom_components",
)


def _snapshot_modules() -> dict[str, object]:
    return {
        name: module
        for name, module in sys.modules.items()
        if name in _RESTORED_MODULE_PREFIXES
        or any(name.startswith(f"{prefix}.") for prefix in _RESTORED_MODULE_PREFIXES)
    }


def _restore_modules(snapshot: dict[str, object]) -> None:
    for name in list(sys.modules):
        if name in _RESTORED_MODULE_PREFIXES or any(
            name.startswith(f"{prefix}.") for prefix in _RESTORED_MODULE_PREFIXES
        ):
            sys.modules.pop(name, None)
    for name, module in snapshot.items():
        if module is not _MISSING:
            sys.modules[name] = module


class _RestoresImportModules:
    """Restore fake modules installed by lightweight config-flow tests."""

    def setUp(self) -> None:
        super().setUp()
        self._module_snapshot = _snapshot_modules()

    def tearDown(self) -> None:
        _restore_modules(self._module_snapshot)
        super().tearDown()


def _install_fake_homeassistant() -> None:
    fake_homeassistant = types.ModuleType("homeassistant")
    fake_homeassistant.const = types.ModuleType("homeassistant.const")
    fake_homeassistant.const.CONF_HOST = "host"
    fake_homeassistant.const.CONF_NAME = "name"
    fake_homeassistant.const.CONF_PORT = "port"

    class _ConfigFlowBase:
        @classmethod
        def __init_subclass__(cls, **kwargs):  # noqa: ANN204
            return super().__init_subclass__()

        def add_suggested_values_to_schema(self, data_schema, suggested_values):  # noqa: ANN001, ANN201
            import copy  # noqa: PLC0415

            schema = {}
            for key, val in data_schema.schema.items():
                new_key = key
                marker_key = getattr(key, "schema", key)
                if suggested_values and marker_key in suggested_values:
                    new_key = copy.copy(key)
                    new_key.description = {
                        "suggested_value": suggested_values[marker_key]
                    }
                schema[new_key] = val
            return data_schema.__class__(schema)

    fake_config_entries = types.ModuleType("homeassistant.config_entries")
    fake_config_entries.ConfigFlow = _ConfigFlowBase
    fake_config_entries.OptionsFlow = _ConfigFlowBase
    fake_config_entries.ConfigFlowResult = dict
    fake_config_entries.ConfigEntry = type("ConfigEntry", (), {})

    fake_core = types.ModuleType("homeassistant.core")
    fake_core.HomeAssistant = type("HomeAssistant", (), {})
    fake_core.callback = lambda func: func

    fake_helpers = types.ModuleType("homeassistant.helpers")
    fake_aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    fake_issue_registry = types.ModuleType("homeassistant.helpers.issue_registry")

    def _async_create_issue(*_args: object, **_kwargs: object) -> None:
        return None

    def _async_delete_issue(*_args: object, **_kwargs: object) -> None:
        return None

    fake_issue_registry.async_create_issue = _async_create_issue
    fake_issue_registry.async_delete_issue = _async_delete_issue

    async def async_get_clientsession(*args, **kwargs):  # noqa: ANN001
        return None

    fake_aiohttp_client.async_get_clientsession = async_get_clientsession
    fake_helpers.aiohttp_client = fake_aiohttp_client
    fake_helpers.issue_registry = fake_issue_registry

    sys.modules["homeassistant"] = fake_homeassistant
    sys.modules["homeassistant.const"] = fake_homeassistant.const
    sys.modules["homeassistant.config_entries"] = fake_config_entries
    sys.modules["homeassistant.core"] = fake_core
    sys.modules["homeassistant.helpers"] = fake_helpers
    sys.modules["homeassistant.helpers.aiohttp_client"] = fake_aiohttp_client
    sys.modules["homeassistant.helpers.issue_registry"] = fake_issue_registry


def _install_fake_voluptuous() -> None:
    """Install a tiny voluptuous substitute for tests without dependency."""

    if "voluptuous" in sys.modules:
        return

    voluptuous = types.ModuleType("voluptuous")

    class _Marker:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.key = args[0] if args else None
            self.default = kwargs.get("default")

    def Required(*args: object, **kwargs: object) -> _Marker:
        return _Marker(*args, **kwargs)

    def Optional(*args: object, **kwargs: object) -> _Marker:
        return _Marker(*args, **kwargs)

    def In(_values: object) -> _Marker:
        return _Marker(_values)

    class Schema:
        def __init__(self, schema: object, *args: object, **kwargs: object) -> None:
            self.schema = schema

        def __call__(self, value: object) -> object:
            return value

    voluptuous.Required = Required
    voluptuous.Optional = Optional
    voluptuous.In = In
    voluptuous.Schema = Schema
    sys.modules["voluptuous"] = voluptuous


def _schema_keys(schema: object) -> set[str]:
    """Return config-flow schema field keys."""
    keys: set[str] = set()
    for marker in getattr(schema, "schema", {}):
        keys.add(getattr(marker, "key", getattr(marker, "schema", None)))
    return keys


def _schema_defaults(schema: object) -> dict[str, object]:
    """Return config-flow schema marker defaults."""
    defaults: dict[str, object] = {}
    for marker in getattr(schema, "schema", {}):
        key = getattr(marker, "key", getattr(marker, "schema", None))
        default = getattr(marker, "default", None)
        if callable(default):
            default = default()
        defaults[key] = default
    return defaults


def _schema_validators(schema: object) -> dict[str, object]:
    """Return config-flow schema validators keyed by field name."""
    validators: dict[str, object] = {}
    for marker, validator in getattr(schema, "schema", {}).items():
        key = getattr(marker, "key", getattr(marker, "schema", None))
        validators[key] = validator
    return validators


def _schema_suggested_values(schema: object) -> dict[str, object]:
    """Return Home Assistant suggested values from a config-flow schema."""
    suggested_values: dict[str, object] = {}
    for marker in getattr(schema, "schema", {}):
        key = getattr(marker, "key", getattr(marker, "schema", None))
        description = getattr(marker, "description", None) or {}
        if "suggested_value" in description:
            suggested_values[key] = description["suggested_value"]
    return suggested_values


def _install_fake_integration_modules() -> None:
    for name in list(sys.modules):
        if name.startswith("custom_components.stiebel_dhe_connect."):
            sys.modules.pop(name, None)

    package_module = types.ModuleType("custom_components")
    package_module.__path__ = [str(PACKAGE_ROOT)]  # type: ignore[attr-defined]
    sys.modules["custom_components"] = package_module

    integration_module = types.ModuleType("custom_components.stiebel_dhe_connect")
    integration_module.__path__ = [str(PACKAGE_ROOT / "stiebel_dhe_connect")]
    sys.modules["custom_components.stiebel_dhe_connect"] = integration_module

    fake_client = types.ModuleType("custom_components.stiebel_dhe_connect.client")
    fake_client.CO2_EMISSION_MAX = 999.0
    fake_client.ELECTRICITY_PRICE_MAX = 999.0
    fake_client.WATER_PRICE_MAX = 999.0
    fake_client.ID_CO2_EMISSION = "id_co2"
    fake_client.ID_ELECTRICITY_PRICE = "id_electricity"
    fake_client.ID_WATER_PRICE = "id_water"
    fake_client.DHEClient = object
    fake_client.DHEError = type("DHEError", (Exception,), {})
    sys.modules["custom_components.stiebel_dhe_connect.client"] = fake_client

    fake_mapping = types.ModuleType(
        "custom_components.stiebel_dhe_connect.config_flow_mapping",
    )
    fake_mapping.default_radio_catalog_value = lambda *args, **kwargs: {}
    fake_mapping.default_weather_country_id = (
        lambda options, default_id: next(iter(options), default_id)
        if isinstance(options, dict)
        else default_id
    )
    fake_mapping.filter_radio_results_by_text = lambda *_args, **_kwargs: []
    fake_mapping.radio_catalog_options = lambda *_args, **_kwargs: {}
    fake_mapping.radio_result_options = lambda *_args, **_kwargs: []
    fake_mapping.weather_country_options = lambda *_args, **_kwargs: {}
    fake_mapping.weather_result_options = lambda *_args, **_kwargs: []
    sys.modules[
        "custom_components.stiebel_dhe_connect.config_flow_mapping"
    ] = fake_mapping

    fake_entry_helpers = types.ModuleType(
        "custom_components.stiebel_dhe_connect.config_entry_helpers",
    )
    def _fake_merged_entry_data(entry):  # noqa: ANN001, ANN202
        data = dict(getattr(entry, "data", {}))
        data.update(getattr(entry, "options", {}))
        return data

    def _fake_entry_target(entry):  # noqa: ANN001, ANN202
        data = _fake_merged_entry_data(entry)
        host = data.get("host")
        if host is None:
            return None
        return str(host), int(data.get("port", 80))

    def _fake_is_target_used_by_other_entry(  # noqa: ANN001, ANN202
        hass,
        host,
        port,
        *,
        exclude_entry_id=None,
    ):
        config_entries = getattr(hass, "config_entries", None)
        if config_entries is None:
            return False
        for entry in config_entries.async_entries("stiebel_dhe_connect"):
            if exclude_entry_id is not None and entry.entry_id == exclude_entry_id:
                continue
            if _fake_entry_target(entry) == (host, port):
                return True
        return False

    fake_entry_helpers.merged_entry_data = _fake_merged_entry_data
    fake_entry_helpers.entry_target = _fake_entry_target
    fake_entry_helpers.is_target_used_by_other_entry = (
        _fake_is_target_used_by_other_entry
    )
    sys.modules["custom_components.stiebel_dhe_connect.config_entry_helpers"] = (
        fake_entry_helpers
    )

    fake_connection = types.ModuleType(
        "custom_components.stiebel_dhe_connect.connection_helpers",
    )
    fake_connection.host_for_url = lambda host: str(host)
    fake_connection.normalize_host = lambda host: str(host)
    fake_connection.target_changed = lambda current, host, port, default_port: (
        current.get("host") != host or current.get("port", default_port) != port
    )
    fake_connection.validate_port = lambda port: int(port)
    sys.modules["custom_components.stiebel_dhe_connect.connection_helpers"] = (
        fake_connection
    )

    fake_const = types.ModuleType("custom_components.stiebel_dhe_connect.const")
    fake_const.DEFAULT_NAME = "DHE"
    fake_const.DEFAULT_PORT = 80
    fake_const.DOMAIN = "stiebel_dhe_connect"
    sys.modules["custom_components.stiebel_dhe_connect.const"] = fake_const

    fake_entity_state = types.ModuleType(
        "custom_components.stiebel_dhe_connect.entity_state_helpers",
    )
    fake_entity_state.CONF_INTERNAL_SCALD_PROTECTION = "internal_scald_protection"
    fake_entity_state.INTERNAL_SCALD_PROTECTION_DEFAULT = "50"
    fake_entity_state.INTERNAL_SCALD_PROTECTION_OPTIONS = (
        "43",
        "50",
        "55",
        "60",
        "no_jumper",
    )
    fake_entity_state.normalize_internal_scald_protection = lambda value: str(
        value or "50"
    )
    sys.modules[
        "custom_components.stiebel_dhe_connect.entity_state_helpers"
    ] = fake_entity_state

    fake_pairing = types.ModuleType("custom_components.stiebel_dhe_connect.pairing_helpers")
    fake_pairing.map_pairing_error = lambda error, *_args: str(error)
    fake_pairing.pairing_notification_text = lambda *_args: ("DHE Pairing", "pairing")
    fake_pairing.pairing_result_success = (
        lambda result: True if str(result).strip().lower() in {"true", "1"} else None
    )
    sys.modules["custom_components.stiebel_dhe_connect.pairing_helpers"] = fake_pairing

    fake_service = types.ModuleType("custom_components.stiebel_dhe_connect.service_helpers")
    fake_service.WEATHER_RESULT_NUMBER_MAX = 50
    sys.modules["custom_components.stiebel_dhe_connect.service_helpers"] = fake_service

    fake_tokens = types.ModuleType(
        "custom_components.stiebel_dhe_connect.token_file_helpers",
    )
    fake_tokens.LEGACY_TOKEN_FILE = ".stiebel_dhe_connect_token.json"

    def _legacy_token_file_for_entry(entry_id: str) -> str:
        return f"legacy_token_{entry_id}.json"

    fake_tokens.legacy_token_file_for_entry = _legacy_token_file_for_entry
    fake_tokens.legacy_token_files_for_target = lambda *_args, **_kwargs: []
    fake_tokens.stale_unconfigured_token_paths = lambda *_args, **_kwargs: []
    fake_tokens.token_file_for_target = lambda host, port: f"token_{host}_{port}.json"

    sys.modules["custom_components.stiebel_dhe_connect.token_file_helpers"] = fake_tokens


def _load_config_flow():
    _install_fake_voluptuous()
    _install_fake_homeassistant()
    _install_fake_integration_modules()

    spec = importlib.util.spec_from_file_location(
        MODULE_NAME,
        CONFIG_FLOW_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load config flow test module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


class TestDeviceSettingsDefaults(_RestoresImportModules, unittest.TestCase):
    """Validate cost and emission settings defaults."""

    def setUp(self) -> None:
        super().setUp()
        self.config_flow = _load_config_flow()

    def test_device_settings_defaults_use_current_numeric_values(self) -> None:
        protocol = sys.modules["custom_components.stiebel_dhe_connect.protocol"]
        client = types.SimpleNamespace(
            last_measurements={
                protocol.ID_ELECTRICITY_PRICE: 0.21,
                protocol.ID_WATER_PRICE: 3.4,
                protocol.ID_CO2_EMISSION: 0.567,
            },
        )

        defaults = self.config_flow._device_settings_defaults(client)

        self.assertEqual(defaults[self.config_flow.ATTR_ELECTRICITY_PRICE], "0.21")
        self.assertEqual(defaults[self.config_flow.ATTR_WATER_PRICE], "3.4")
        self.assertEqual(defaults[self.config_flow.ATTR_CO2_EMISSION], "0.567")

    def test_device_settings_defaults_use_blank_when_values_are_missing(self) -> None:
        client = types.SimpleNamespace(last_measurements={})

        defaults = self.config_flow._device_settings_defaults(client)

        self.assertEqual(defaults[self.config_flow.ATTR_ELECTRICITY_PRICE], "")
        self.assertEqual(defaults[self.config_flow.ATTR_WATER_PRICE], "")
        self.assertEqual(defaults[self.config_flow.ATTR_CO2_EMISSION], "")


class TestDiscoveryDisplayNames(_RestoresImportModules, unittest.TestCase):
    """Validate user-facing names derived from discovery payloads."""

    def setUp(self) -> None:
        super().setUp()
        self.config_flow = _load_config_flow()

    def test_discovery_name_prefers_device_property(self) -> None:
        info = types.SimpleNamespace(
            name="_ste-dhe._tcp.local.",
            hostname="dhe-ja06.local.",
            host="192.0.2.124",
            ip_address="192.0.2.124",
            properties={b"name": b"Bathroom DHE"},
        )

        self.assertEqual(self.config_flow._discovery_info_name(info), "Bathroom DHE")

    def test_discovery_name_ignores_technical_domain_fallback(self) -> None:
        info = types.SimpleNamespace(
            name="stiebel_dhe_connect",
            hostname=None,
            host="dhe-ja06.local.",
            ip_address="192.0.2.124",
            properties={},
        )

        self.assertEqual(self.config_flow._discovery_info_name(info), "dhe-ja06")

    def test_discovery_name_uses_per_target_ip_fallback(self) -> None:
        info = types.SimpleNamespace(
            name="_ste-dhe._tcp.local.",
            hostname=None,
            host="192.0.2.124",
            ip_address="192.0.2.124",
            properties={},
        )

        self.assertEqual(
            self.config_flow._discovery_info_name(info),
            f"{self.config_flow.DEFAULT_NAME} 192.0.2.124",
        )


class TestDeviceSettingsOptionsFlow(
    _RestoresImportModules,
    unittest.IsolatedAsyncioTestCase,
):
    """Validate device settings options flow writes only explicit values."""

    def setUp(self) -> None:
        super().setUp()
        self.config_flow = _load_config_flow()
        self.flow = self.config_flow.StiebelDHEConnectOptionsFlow()
        self.entry_id = "entry-device-settings"
        self.client = types.SimpleNamespace(
            set_electricity_price=AsyncMock(),
            set_water_price=AsyncMock(),
            set_co2_emission=AsyncMock(),
        )
        self.config_entry = types.SimpleNamespace(
            entry_id=self.entry_id,
            options={},
            runtime_data=types.SimpleNamespace(client=self.client),
        )
        self.flow.config_entry = self.config_entry
        self.flow.hass = types.SimpleNamespace(
            data={},
            config=types.SimpleNamespace(language="en"),
        )
        self.flow.async_create_entry = types.MethodType(
            lambda _self, **kwargs: {
                "type": "create_entry",
                "title": kwargs.get("title"),
                "data": kwargs.get("data", {}),
            },
            self.flow,
        )

    async def test_device_settings_writes_only_provided_values(
        self,
    ) -> None:
        user_input = {self.config_flow.ATTR_ELECTRICITY_PRICE: "0.21"}

        result = await self.flow.async_step_device_settings(user_input=user_input)

        self.assertEqual(result["data"], {})
        self.client.set_electricity_price.assert_awaited_once_with(0.21)
        self.client.set_water_price.assert_not_awaited()
        self.client.set_co2_emission.assert_not_awaited()


class TestConnectionOptionsConnectivity(
    _RestoresImportModules,
    unittest.IsolatedAsyncioTestCase,
):
    """Check options flow connection step connectivity policy."""

    def setUp(self) -> None:
        super().setUp()
        self.config_flow = _load_config_flow()
        self.flow = self.config_flow.StiebelDHEConnectOptionsFlow()
        self.entry_id = "entry-connection-options"
        self.config_entry = types.SimpleNamespace(
            entry_id=self.entry_id,
            data={
                "host": "dhe.local",
                "port": 80,
                "name": "DHE",
                self.config_flow.CONF_INTERNAL_SCALD_PROTECTION: "50",
            },
            options={},
        )

        class _ConfigEntries:
            def __init__(self, entries: list[types.SimpleNamespace]) -> None:
                self._entries = entries

            def async_entries(self, _domain: str):  # noqa: ANN001
                return self._entries

        self.flow.config_entry = self.config_entry

        async def _async_add_executor_job(func, *args):  # noqa: ANN001
            return func(*args)

        self.flow.hass = types.SimpleNamespace(
            config=types.SimpleNamespace(
                language="en",
                path=lambda path: str(ROOT / ".tmp-test-config" / path),
            ),
            config_entries=_ConfigEntries([]),
            data={},
            async_add_executor_job=_async_add_executor_job,
        )
        self.flow.async_show_form = types.MethodType(
            lambda _self, **kwargs: {
                "type": "form",
                "step_id": kwargs.get("step_id"),
                "data_schema": kwargs.get("data_schema"),
                "errors": kwargs.get("errors", {}),
            },
            self.flow,
        )
        self.flow.async_create_entry = types.MethodType(
            lambda _self, **kwargs: {
                "type": "create_entry",
                "title": kwargs.get("title"),
                "data": kwargs.get("data", {}),
            },
            self.flow,
        )

    async def test_connection_step_skips_connectivity_when_target_unchanged(
        self,
    ) -> None:
        self.config_flow._can_connect = AsyncMock(return_value=False)

        result = await self.flow.async_step_connection(
            {
                self.config_flow.CONF_HOST: "dhe.local",
                self.config_flow.CONF_PORT: 80,
                self.config_flow.CONF_NAME: "DHE 2",
                self.config_flow.CONF_INTERNAL_SCALD_PROTECTION: "55",
            },
        )

        self.config_flow._can_connect.assert_not_awaited()
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"][self.config_flow.CONF_HOST], "dhe.local")
        self.assertEqual(result["data"][self.config_flow.CONF_NAME], "DHE 2")
        self.assertEqual(
            result["data"][self.config_flow.CONF_INTERNAL_SCALD_PROTECTION], "55"
        )

    async def test_connection_step_checks_connectivity_when_target_changed(self) -> None:
        self.config_flow._can_connect = AsyncMock(return_value=False)

        result = await self.flow.async_step_connection(
            {
                self.config_flow.CONF_HOST: "other.local",
                self.config_flow.CONF_PORT: 80,
                self.config_flow.CONF_NAME: "DHE 2",
                self.config_flow.CONF_INTERNAL_SCALD_PROTECTION: "50",
            },
        )

        self.config_flow._can_connect.assert_awaited_once_with(
            self.flow.hass,
            "other.local",
            80,
        )
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "connection")
        self.assertEqual(result["errors"]["base"], "cannot_connect")
        defaults = _schema_defaults(result["data_schema"])
        self.assertEqual(defaults[self.config_flow.CONF_HOST], "other.local")
        self.assertEqual(defaults[self.config_flow.CONF_PORT], 80)
        self.assertEqual(defaults[self.config_flow.CONF_NAME], "DHE 2")
        self.assertEqual(
            defaults[self.config_flow.CONF_INTERNAL_SCALD_PROTECTION],
            "50",
        )

    async def test_connection_step_updates_options_when_target_changed_and_connects(
        self,
    ) -> None:
        self.config_flow._can_connect = AsyncMock(return_value=True)

        result = await self.flow.async_step_connection(
            {
                self.config_flow.CONF_HOST: "other.local",
                self.config_flow.CONF_PORT: 80,
                self.config_flow.CONF_NAME: "DHE 2",
                self.config_flow.CONF_INTERNAL_SCALD_PROTECTION: "50",
            },
        )

        self.config_flow._can_connect.assert_awaited_once_with(
            self.flow.hass,
            "other.local",
            80,
        )
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"][self.config_flow.CONF_HOST], "other.local")
        self.assertEqual(result["data"][self.config_flow.CONF_NAME], "DHE 2")


class TestSetupScanConfigFlow(
    _RestoresImportModules,
    unittest.IsolatedAsyncioTestCase,
):
    """Check optional setup scan flow behavior."""

    def setUp(self) -> None:
        super().setUp()
        self.config_flow = _load_config_flow()
        self.flow = self.config_flow.StiebelDHEConnectConfigFlow()

        class _FlowManager:
            def __init__(self) -> None:
                self.progress: list[dict[str, object]] = []
                self.aborted: list[str] = []

            def async_progress_by_handler(self, _domain: str):  # noqa: ANN001
                return list(self.progress)

            def async_abort(self, flow_id: str) -> None:
                self.aborted.append(flow_id)

        class _ConfigEntries:
            def __init__(self, flow_manager: _FlowManager) -> None:
                self.flow = flow_manager

            def async_entries(self, _domain: str):  # noqa: ANN001
                return []

        self._flow_manager = _FlowManager()
        self._tasks: list[asyncio.Task] = []

        def _create_task(coro):  # noqa: ANN001
            task = asyncio.create_task(coro)
            self._tasks.append(task)
            return task

        async def _add_executor_job(func, *args):  # noqa: ANN001
            return func(*args)

        self.flow.hass = types.SimpleNamespace(
            async_add_executor_job=_add_executor_job,
            async_create_task=_create_task,
            config=types.SimpleNamespace(language="en"),
            config_entries=_ConfigEntries(self._flow_manager),
        )
        self.flow.async_show_progress = types.MethodType(
            lambda _self, **kwargs: {
                "type": "progress",
                "step_id": kwargs.get("step_id"),
                "progress_action": kwargs.get("progress_action"),
            },
            self.flow,
        )
        self.flow.async_show_progress_done = types.MethodType(
            lambda _self, **kwargs: {
                "type": "progress_done",
                "step_id": kwargs.get("next_step_id"),
            },
            self.flow,
        )
        self.flow.async_show_form = types.MethodType(
            lambda _self, **kwargs: {
                "type": "form",
                "step_id": kwargs.get("step_id"),
                "data_schema": kwargs.get("data_schema"),
                "description_placeholders": kwargs.get("description_placeholders", {}),
                "errors": kwargs.get("errors", {}),
            },
            self.flow,
        )

    async def test_user_step_shows_setup_choice_before_scan(self) -> None:
        self.config_flow.async_scan_dhe_hosts = AsyncMock(return_value=[])

        result = await self.flow.async_step_user()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "user")
        self.config_flow.async_scan_dhe_hosts.assert_not_called()
        defaults = _schema_defaults(result["data_schema"])
        self.assertEqual(
            defaults[self.config_flow.CONF_SETUP_MODE],
            self.config_flow.SETUP_MODE_SCAN,
        )
        self.assertNotIn(self.config_flow.CONF_SCAN_NETWORK_ADDRESS, defaults)
        self.assertNotIn(self.config_flow.CONF_SCAN_NETMASK, defaults)
        self.assertNotIn(self.config_flow.CONF_SCAN_CIDR, defaults)

    async def test_user_step_lists_zeroconf_choices_before_scan_and_manual(self) -> None:
        self._flow_manager.progress = [
            {
                "flow_id": "zeroconf-flow",
                "context": {
                    "source": "zeroconf",
                    self.config_flow.FLOW_CONTEXT_DISCOVERED_HOST: "192.0.2.124",
                    self.config_flow.FLOW_CONTEXT_DISCOVERED_PORT: 8443,
                    self.config_flow.FLOW_CONTEXT_DISCOVERY_NAME: "DHE-JA06",
                },
            }
        ]

        result = await self.flow.async_step_user()

        defaults = _schema_defaults(result["data_schema"])
        validators = _schema_validators(result["data_schema"])
        setup_validator = validators[self.config_flow.CONF_SETUP_MODE]
        if hasattr(setup_validator, "container") and setup_validator.container is not None:
            setup_options_source = setup_validator.container
        else:
            setup_options_source = setup_validator.key
        setup_options = list(
            setup_options_source
        )
        self.assertEqual(
            defaults[self.config_flow.CONF_SETUP_MODE],
            self.config_flow.SETUP_MODE_SCAN,
        )
        self.assertEqual(
            setup_options[:3],
            [
                "zeroconf:192.0.2.124:8443",
                self.config_flow.SETUP_MODE_SCAN,
                self.config_flow.SETUP_MODE_MANUAL,
            ],
        )

    async def test_discovered_setup_sets_title_placeholder(self) -> None:
        self.config_flow._can_connect = AsyncMock(return_value=True)
        self.flow.context = {}

        result = await self.flow._async_start_discovered_setup(
            "192.0.2.124",
            8443,
            "DHE-JA06",
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "zeroconf_confirm")
        self.assertEqual(self.flow.context["title_placeholders"], {"name": "DHE-JA06"})

    async def test_user_step_ignores_non_zeroconf_progress_contexts(self) -> None:
        self._flow_manager.progress = [
            {
                "flow_id": "user-flow",
                "context": {
                    "source": "user",
                    self.config_flow.FLOW_CONTEXT_DISCOVERED_HOST: "192.0.2.124",
                    self.config_flow.FLOW_CONTEXT_DISCOVERED_PORT: 8443,
                    self.config_flow.FLOW_CONTEXT_DISCOVERY_NAME: "DHE-JA06",
                },
            }
        ]

        result = await self.flow.async_step_user()

        validators = _schema_validators(result["data_schema"])
        setup_validator = validators[self.config_flow.CONF_SETUP_MODE]
        if hasattr(setup_validator, "container") and setup_validator.container is not None:
            setup_options_source = setup_validator.container
        else:
            setup_options_source = setup_validator.key
        setup_options = list(
            setup_options_source
        )
        self.assertEqual(
            setup_options,
            [
                self.config_flow.SETUP_MODE_SCAN,
                self.config_flow.SETUP_MODE_MANUAL,
            ],
        )

    async def test_subnet_scan_forms_keep_subnet_alternatives_separate(self) -> None:
        self.config_flow.local_ipv4_addresses_from_hass = lambda _hass: [
            "192.168.2.147"
        ]

        result = await self.flow.async_step_user(
            {self.config_flow.CONF_SETUP_MODE: self.config_flow.SETUP_MODE_SCAN}
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "subnet_scan")
        defaults = _schema_defaults(result["data_schema"])
        keys = _schema_keys(result["data_schema"])
        self.assertEqual(
            defaults[self.config_flow.CONF_SCAN_SUBNET_MODE],
            self.config_flow.SCAN_SUBNET_MODE_CURRENT,
        )
        self.assertEqual(
            defaults[self.config_flow.CONF_SCAN_PORT],
            self.config_flow.DEFAULT_PORT,
        )
        self.assertNotIn(self.config_flow.CONF_SCAN_NETWORK_ADDRESS, keys)
        self.assertNotIn(self.config_flow.CONF_SCAN_NETMASK, keys)
        self.assertNotIn(self.config_flow.CONF_SCAN_CIDR, keys)

        result = await self.flow.async_step_subnet_scan(
            {
                self.config_flow.CONF_SCAN_SUBNET_MODE: (
                    self.config_flow.SCAN_SUBNET_MODE_NETWORK_MASK
                )
            }
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "subnet_scan_network_mask")
        suggested_values = _schema_suggested_values(result["data_schema"])
        self.assertEqual(
            suggested_values[self.config_flow.CONF_SCAN_NETWORK_ADDRESS],
            "192.168.2.0",
        )
        self.assertEqual(
            suggested_values[self.config_flow.CONF_SCAN_NETMASK],
            "255.255.255.0",
        )
        self.assertNotIn(
            self.config_flow.CONF_SCAN_CIDR,
            _schema_keys(result["data_schema"]),
        )

        result = await self.flow.async_step_subnet_scan(
            {
                self.config_flow.CONF_SCAN_SUBNET_MODE: (
                    self.config_flow.SCAN_SUBNET_MODE_CIDR
                )
            }
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "subnet_scan_cidr")
        suggested_values = _schema_suggested_values(result["data_schema"])
        self.assertEqual(
            suggested_values[self.config_flow.CONF_SCAN_CIDR],
            "192.168.2.0/24",
        )
        keys = _schema_keys(result["data_schema"])
        self.assertNotIn(self.config_flow.CONF_SCAN_NETWORK_ADDRESS, keys)
        self.assertNotIn(self.config_flow.CONF_SCAN_NETMASK, keys)

    async def test_user_step_manual_choice_shows_manual_form_without_scan(self) -> None:
        self.config_flow.async_scan_dhe_hosts = AsyncMock(return_value=[])

        result = await self.flow.async_step_user(
            {self.config_flow.CONF_SETUP_MODE: self.config_flow.SETUP_MODE_MANUAL}
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "manual")
        self.assertIn(
            "Enter host/IP",
            result["description_placeholders"]["scan_status"],
        )
        self.config_flow.async_scan_dhe_hosts.assert_not_called()

    async def test_user_step_scan_uses_custom_subnet(self) -> None:
        self.config_flow.async_scan_dhe_hosts = AsyncMock(return_value=[])

        result = await self.flow.async_step_user(
            {self.config_flow.CONF_SETUP_MODE: self.config_flow.SETUP_MODE_SCAN}
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "subnet_scan")
        result = await self.flow.async_step_subnet_scan(
            {
                self.config_flow.CONF_SCAN_SUBNET_MODE: (
                    self.config_flow.SCAN_SUBNET_MODE_NETWORK_MASK
                )
            }
        )
        self.assertEqual(result["step_id"], "subnet_scan_network_mask")
        result = await self.flow.async_step_subnet_scan_network_mask(
            {
                self.config_flow.CONF_SCAN_NETWORK_ADDRESS: "192.168.2.0",
                self.config_flow.CONF_SCAN_NETMASK: "255.255.255.0",
            }
        )

        self.assertEqual(result["type"], "progress")
        await self._tasks[0]
        self.config_flow.async_scan_dhe_hosts.assert_awaited_once_with(
            self.flow.hass,
            networks=[ip_network("192.168.2.0/24")],
            port=self.config_flow.DEFAULT_PORT,
        )

    async def test_user_step_scan_uses_custom_scan_port(self) -> None:
        self.config_flow.async_scan_dhe_hosts = AsyncMock(return_value=[])

        result = await self.flow.async_step_user(
            {self.config_flow.CONF_SETUP_MODE: self.config_flow.SETUP_MODE_SCAN}
        )
        self.assertEqual(result["step_id"], "subnet_scan")

        result = await self.flow.async_step_subnet_scan(
            {
                self.config_flow.CONF_SCAN_SUBNET_MODE: (
                    self.config_flow.SCAN_SUBNET_MODE_CURRENT
                ),
                self.config_flow.CONF_SCAN_PORT: 9443,
            }
        )

        self.assertEqual(result["type"], "progress")
        await self._tasks[0]
        self.config_flow.async_scan_dhe_hosts.assert_awaited_once_with(
            self.flow.hass,
            networks=None,
            port=9443,
        )

    async def test_user_step_scan_rejects_invalid_scan_port(self) -> None:
        self.config_flow.async_scan_dhe_hosts = AsyncMock(return_value=[])

        result = await self.flow.async_step_user(
            {self.config_flow.CONF_SETUP_MODE: self.config_flow.SETUP_MODE_SCAN}
        )
        self.assertEqual(result["step_id"], "subnet_scan")

        result = await self.flow.async_step_subnet_scan(
            {
                self.config_flow.CONF_SCAN_SUBNET_MODE: (
                    self.config_flow.SCAN_SUBNET_MODE_CURRENT
                ),
                self.config_flow.CONF_SCAN_PORT: "not-a-port",
            }
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "subnet_scan")
        self.assertEqual(
            result["errors"][self.config_flow.CONF_SCAN_PORT],
            "invalid_port",
        )
        self.config_flow.async_scan_dhe_hosts.assert_not_called()

    async def test_user_step_scan_uses_cidr_subnet(self) -> None:
        self.config_flow.async_scan_dhe_hosts = AsyncMock(return_value=[])

        result = await self.flow.async_step_user(
            {self.config_flow.CONF_SETUP_MODE: self.config_flow.SETUP_MODE_SCAN}
        )

        self.assertEqual(result["step_id"], "subnet_scan")
        result = await self.flow.async_step_subnet_scan(
            {
                self.config_flow.CONF_SCAN_SUBNET_MODE: (
                    self.config_flow.SCAN_SUBNET_MODE_CIDR
                )
            }
        )
        self.assertEqual(result["step_id"], "subnet_scan_cidr")
        result = await self.flow.async_step_subnet_scan_cidr(
            {
                self.config_flow.CONF_SCAN_CIDR: "192.168.2.0/25",
            }
        )

        self.assertEqual(result["type"], "progress")
        await self._tasks[0]
        self.config_flow.async_scan_dhe_hosts.assert_awaited_once_with(
            self.flow.hass,
            networks=[ip_network("192.168.2.0/25")],
            port=self.config_flow.DEFAULT_PORT,
        )

    async def test_user_step_scan_uses_current_local_subnet_mode(self) -> None:
        self.config_flow.async_scan_dhe_hosts = AsyncMock(return_value=[])

        result = await self.flow.async_step_user(
            {self.config_flow.CONF_SETUP_MODE: self.config_flow.SETUP_MODE_SCAN}
        )
        self.assertEqual(result["step_id"], "subnet_scan")
        result = await self.flow.async_step_subnet_scan(
            {
                self.config_flow.CONF_SCAN_SUBNET_MODE: (
                    self.config_flow.SCAN_SUBNET_MODE_CURRENT
                )
            }
        )

        self.assertEqual(result["type"], "progress")
        await self._tasks[0]
        self.config_flow.async_scan_dhe_hosts.assert_awaited_once_with(
            self.flow.hass,
            networks=None,
            port=self.config_flow.DEFAULT_PORT,
        )

    async def test_user_step_scan_rejects_invalid_subnet(self) -> None:
        self.config_flow.async_scan_dhe_hosts = AsyncMock(return_value=[])

        result = await self.flow.async_step_user(
            {self.config_flow.CONF_SETUP_MODE: self.config_flow.SETUP_MODE_SCAN}
        )

        self.assertEqual(result["step_id"], "subnet_scan")
        result = await self.flow.async_step_subnet_scan(
            {
                self.config_flow.CONF_SCAN_SUBNET_MODE: (
                    self.config_flow.SCAN_SUBNET_MODE_NETWORK_MASK
                )
            }
        )
        self.assertEqual(result["step_id"], "subnet_scan_network_mask")
        result = await self.flow.async_step_subnet_scan_network_mask(
            {
                self.config_flow.CONF_SCAN_NETWORK_ADDRESS: "192.168.0.0",
                self.config_flow.CONF_SCAN_NETMASK: "255.255.0.0",
            }
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "subnet_scan_network_mask")
        self.assertEqual(
            result["errors"][self.config_flow.CONF_SCAN_NETMASK],
            "scan_subnet_too_large",
        )
        self.config_flow.async_scan_dhe_hosts.assert_not_called()

    async def test_user_step_scan_rejects_empty_network_mask_on_visible_field(
        self,
    ) -> None:
        self.config_flow.async_scan_dhe_hosts = AsyncMock(return_value=[])

        result = await self.flow.async_step_user(
            {self.config_flow.CONF_SETUP_MODE: self.config_flow.SETUP_MODE_SCAN}
        )

        self.assertEqual(result["step_id"], "subnet_scan")
        result = await self.flow.async_step_subnet_scan(
            {
                self.config_flow.CONF_SCAN_SUBNET_MODE: (
                    self.config_flow.SCAN_SUBNET_MODE_NETWORK_MASK
                )
            }
        )
        self.assertEqual(result["step_id"], "subnet_scan_network_mask")
        result = await self.flow.async_step_subnet_scan_network_mask(
            {
                self.config_flow.CONF_SCAN_NETWORK_ADDRESS: "",
                self.config_flow.CONF_SCAN_NETMASK: "",
            }
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "subnet_scan_network_mask")
        self.assertEqual(
            result["errors"][self.config_flow.CONF_SCAN_NETWORK_ADDRESS],
            "invalid_scan_subnet",
        )
        self.config_flow.async_scan_dhe_hosts.assert_not_called()

    async def test_user_step_scan_rejects_wildcard_netmask(self) -> None:
        self.config_flow.async_scan_dhe_hosts = AsyncMock(return_value=[])

        result = await self.flow.async_step_user(
            {self.config_flow.CONF_SETUP_MODE: self.config_flow.SETUP_MODE_SCAN}
        )

        self.assertEqual(result["step_id"], "subnet_scan")
        result = await self.flow.async_step_subnet_scan(
            {
                self.config_flow.CONF_SCAN_SUBNET_MODE: (
                    self.config_flow.SCAN_SUBNET_MODE_NETWORK_MASK
                )
            }
        )
        self.assertEqual(result["step_id"], "subnet_scan_network_mask")
        result = await self.flow.async_step_subnet_scan_network_mask(
            {
                self.config_flow.CONF_SCAN_NETWORK_ADDRESS: "192.168.2.0",
                self.config_flow.CONF_SCAN_NETMASK: "0.0.0.255",
            }
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "subnet_scan_network_mask")
        self.assertEqual(
            result["errors"][self.config_flow.CONF_SCAN_NETMASK],
            "invalid_scan_subnet",
        )
        self.config_flow.async_scan_dhe_hosts.assert_not_called()

    async def test_user_step_scan_rejects_slash_wildcard_netmask(self) -> None:
        self.config_flow.async_scan_dhe_hosts = AsyncMock(return_value=[])

        result = await self.flow.async_step_user(
            {self.config_flow.CONF_SETUP_MODE: self.config_flow.SETUP_MODE_SCAN}
        )

        self.assertEqual(result["step_id"], "subnet_scan")
        result = await self.flow.async_step_subnet_scan(
            {
                self.config_flow.CONF_SCAN_SUBNET_MODE: (
                    self.config_flow.SCAN_SUBNET_MODE_CIDR
                )
            }
        )
        self.assertEqual(result["step_id"], "subnet_scan_cidr")
        result = await self.flow.async_step_subnet_scan_cidr(
            {
                self.config_flow.CONF_SCAN_CIDR: "192.168.2.0/0.0.0.255",
            }
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "subnet_scan_cidr")
        self.assertEqual(
            result["errors"][self.config_flow.CONF_SCAN_CIDR],
            "invalid_scan_subnet",
        )
        self.config_flow.async_scan_dhe_hosts.assert_not_called()

    async def test_user_step_runs_scan_then_prefills_manual_form(self) -> None:
        self.config_flow.async_scan_dhe_hosts = AsyncMock(
            return_value=[
                types.SimpleNamespace(
                    host="192.0.2.124",
                    port=8443,
                    evidence=("STE DHE App",),
                )
            ]
        )

        result = await self.flow.async_step_user(
            {self.config_flow.CONF_SETUP_MODE: self.config_flow.SETUP_MODE_SCAN}
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "subnet_scan")
        result = await self.flow.async_step_subnet_scan(
            {
                self.config_flow.CONF_SCAN_SUBNET_MODE: (
                    self.config_flow.SCAN_SUBNET_MODE_CURRENT
                )
            }
        )

        self.assertEqual(result["type"], "progress")
        self.assertEqual(result["step_id"], "network_scan")
        self.assertEqual(result["progress_action"], "scan_dhe")
        await self._tasks[0]

        result = await self.flow.async_step_network_scan({})

        self.assertEqual(result["type"], "progress_done")

        result = await self.flow.async_step_manual()

        defaults = _schema_defaults(result["data_schema"])
        self.assertEqual(defaults[self.config_flow.CONF_HOST], "192.0.2.124")
        self.assertEqual(defaults[self.config_flow.CONF_PORT], 8443)
        self.assertIn("Found one DHE", result["description_placeholders"]["scan_status"])

    async def test_user_step_falls_back_to_manual_form_when_scan_finds_nothing(
        self,
    ) -> None:
        self.config_flow.async_scan_dhe_hosts = AsyncMock(return_value=[])

        result = await self.flow.async_step_user(
            {self.config_flow.CONF_SETUP_MODE: self.config_flow.SETUP_MODE_SCAN}
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "subnet_scan")
        result = await self.flow.async_step_subnet_scan(
            {
                self.config_flow.CONF_SCAN_SUBNET_MODE: (
                    self.config_flow.SCAN_SUBNET_MODE_CURRENT
                )
            }
        )

        self.assertEqual(result["type"], "progress")
        await self._tasks[0]
        result = await self.flow.async_step_network_scan()
        self.assertEqual(result["type"], "progress_done")
        result = await self.flow.async_step_manual()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "manual")
        self.assertIn("No DHE", result["description_placeholders"]["scan_status"])

    async def test_network_scan_treats_empty_progress_poll_as_scan_poll(self) -> None:
        self.config_flow.async_scan_dhe_hosts = AsyncMock(return_value=[])

        result = await self.flow.async_step_network_scan()

        self.assertEqual(result["type"], "progress")
        await self._tasks[0]
        result = await self.flow.async_step_network_scan({})
        self.assertEqual(result["type"], "progress_done")
        result = await self.flow.async_step_manual({})

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"], {})


class TestSetupPairingValidation(
    _RestoresImportModules,
    unittest.IsolatedAsyncioTestCase,
):
    """Validate setup-pairing error mapping."""

    def setUp(self) -> None:
        super().setUp()
        self.config_flow = _load_config_flow()

    async def test_validate_setup_pairing_maps_runtime_transport_errors(self) -> None:
        module = self.config_flow
        module._async_clear_setup_token_files = AsyncMock()
        module.map_pairing_error = (
            lambda error, pairing_state: f"{pairing_state}: {error}"
        )

        class _FakeClient:
            diagnostic_state = {"pairing_state": "requesting_token"}

            def __init__(self, **_kwargs: object) -> None:
                pass

            async def validate_setup_authentication(
                self,
                *,
                timeout_seconds: float,
            ) -> None:
                raise RuntimeError("websocket closed")

        module.DHEClient = _FakeClient

        result = await module._validate_setup_pairing(
            object(),
            "192.0.2.124",
            80,
            "token.json",
        )

        self.assertEqual(result.error_key, "requesting_token: websocket closed")
        self.assertIsNone(result.unique_id)

    async def test_validate_setup_pairing_returns_mac_unique_id(self) -> None:
        module = self.config_flow
        module._async_clear_setup_token_files = AsyncMock()

        class _FakeClient:
            diagnostic_state: dict[str, object] = {}
            last_device_info = {"wlan_mac": "AA-BB-CC-DD-EE-FF"}

            def __init__(self, **_kwargs: object) -> None:
                pass

            async def validate_setup_authentication(
                self,
                *,
                timeout_seconds: float,
            ) -> None:
                return None

        module.DHEClient = _FakeClient

        result = await module._validate_setup_pairing(
            object(),
            "192.0.2.124",
            80,
            "token.json",
        )

        self.assertIsNone(result.error_key)
        self.assertEqual(result.unique_id, "aa:bb:cc:dd:ee:ff")


class TestManifestZeroconf(_RestoresImportModules, unittest.TestCase):
    """Validate manifest discovery metadata."""

    def test_manifest_declares_zeroconf_config_flow_handler(self) -> None:
        config_flow = _load_config_flow()
        manifest = json.loads(
            (
                ROOT
                / "custom_components"
                / "stiebel_dhe_connect"
                / "manifest.json"
            ).read_text(encoding="utf-8")
        )

        self.assertTrue(manifest["config_flow"])
        self.assertIn("_ste-dhe._tcp.local.", manifest["zeroconf"])
        self.assertTrue(
            hasattr(config_flow.StiebelDHEConnectConfigFlow, "async_step_zeroconf")
        )
