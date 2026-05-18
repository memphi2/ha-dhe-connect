"""Tests for config flow device settings defaults."""

from __future__ import annotations

import asyncio
import importlib.util
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

    async def async_get_clientsession(*args, **kwargs):  # noqa: ANN001
        return None

    fake_aiohttp_client.async_get_clientsession = async_get_clientsession
    fake_helpers.aiohttp_client = fake_aiohttp_client

    sys.modules["homeassistant"] = fake_homeassistant
    sys.modules["homeassistant.const"] = fake_homeassistant.const
    sys.modules["homeassistant.config_entries"] = fake_config_entries
    sys.modules["homeassistant.core"] = fake_core
    sys.modules["homeassistant.helpers"] = fake_helpers
    sys.modules["homeassistant.helpers.aiohttp_client"] = fake_aiohttp_client


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


def _install_fake_integration_modules() -> None:
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
    fake_client.ID_APP_CURRENCY = "app_currency"
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
    fake_entry_helpers.merged_entry_data = lambda entry: getattr(entry, "data", {})
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
    """Validate currency fallbacks for device settings defaults."""

    def setUp(self) -> None:
        super().setUp()
        self.config_flow = _load_config_flow()

    def test_device_settings_defaults_uses_device_currency_when_available(self) -> None:
        client = types.SimpleNamespace(
            last_measurements={self.config_flow.ID_APP_CURRENCY: "gbp"},
        )

        defaults = self.config_flow._device_settings_defaults(client)

        self.assertEqual(defaults[self.config_flow.ATTR_CURRENCY], "GBP")

    def test_device_settings_defaults_uses_unchanged_when_currency_missing(self) -> None:
        client = types.SimpleNamespace(last_measurements={})

        defaults = self.config_flow._device_settings_defaults(client)

        self.assertEqual(
            defaults[self.config_flow.ATTR_CURRENCY],
            self.config_flow.CURRENCY_UNCHANGED,
        )

    def test_device_settings_defaults_uses_unchanged_when_currency_is_unset(self) -> None:
        client = types.SimpleNamespace(
            last_measurements={self.config_flow.ID_APP_CURRENCY: "UNSET"},
        )

        defaults = self.config_flow._device_settings_defaults(client)

        self.assertEqual(
            defaults[self.config_flow.ATTR_CURRENCY],
            self.config_flow.CURRENCY_UNCHANGED,
        )

    def test_device_settings_defaults_uses_unchanged_when_currency_not_supported(self) -> None:
        client = types.SimpleNamespace(
            last_measurements={self.config_flow.ID_APP_CURRENCY: "JPY"},
        )

        defaults = self.config_flow._device_settings_defaults(client)

        self.assertEqual(
            defaults[self.config_flow.ATTR_CURRENCY],
            self.config_flow.CURRENCY_UNCHANGED,
        )

    def test_currency_options_keep_german_unchanged_label_utf8(self) -> None:
        hass = types.SimpleNamespace(config=types.SimpleNamespace(language="de"))

        options = self.config_flow._currency_options(hass)

        label = options[self.config_flow.CURRENCY_UNCHANGED]
        self.assertEqual(label, "Nicht ändern")
        self.assertNotIn("Ã", label)


class TestDeviceSettingsOptionsFlow(
    _RestoresImportModules,
    unittest.IsolatedAsyncioTestCase,
):
    """Validate device settings options flow does not write unchanged currency."""

    def setUp(self) -> None:
        super().setUp()
        self.config_flow = _load_config_flow()
        self.flow = self.config_flow.StiebelDHEConnectOptionsFlow()
        self.entry_id = "entry-device-settings"
        self.client = types.SimpleNamespace(
            set_currency=AsyncMock(),
            set_electricity_price=AsyncMock(),
            set_water_price=AsyncMock(),
            set_co2_emission=AsyncMock(),
        )
        self.config_entry = types.SimpleNamespace(
            entry_id=self.entry_id,
            options={},
        )
        self.flow.config_entry = self.config_entry
        self.flow.hass = types.SimpleNamespace(
            data={
                self.config_flow.DOMAIN: {
                    self.entry_id: types.SimpleNamespace(client=self.client),
                }
            },
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

    async def test_device_settings_does_not_write_currency_without_explicit_change(
        self,
    ) -> None:
        user_input = {self.config_flow.ATTR_ELECTRICITY_PRICE: "0.21"}

        result = await self.flow.async_step_device_settings(user_input=user_input)

        self.assertEqual(result["data"], {})
        self.client.set_currency.assert_not_awaited()
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
        self.flow.hass = types.SimpleNamespace(
            config=types.SimpleNamespace(language="en"),
            config_entries=_ConfigEntries([]),
            data={},
        )
        self.flow.async_show_form = types.MethodType(
            lambda _self, **kwargs: {
                "type": "form",
                "step_id": kwargs.get("step_id"),
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

    async def test_connection_step_enters_pairing_when_target_changed_and_connects(
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
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "connection_pairing_confirm")


class TestSetupScanConfigFlow(
    _RestoresImportModules,
    unittest.IsolatedAsyncioTestCase,
):
    """Check optional setup scan flow behavior."""

    def setUp(self) -> None:
        super().setUp()
        self.config_flow = _load_config_flow()
        self.flow = self.config_flow.StiebelDHEConnectConfigFlow()

        class _ConfigEntries:
            def async_entries(self, _domain: str):  # noqa: ANN001
                return []

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
            config_entries=_ConfigEntries(),
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
        defaults = {}
        for marker in result["data_schema"].schema:
            key = getattr(marker, "key", getattr(marker, "schema", None))
            default = getattr(marker, "default", None)
            if callable(default):
                default = default()
            defaults[key] = default
        self.assertFalse(defaults[self.config_flow.CONF_SCAN_AUTOMATICALLY])
        self.assertNotIn(self.config_flow.CONF_SCAN_NETWORK_ADDRESS, defaults)
        self.assertNotIn(self.config_flow.CONF_SCAN_NETMASK, defaults)
        self.assertNotIn(self.config_flow.CONF_SCAN_CIDR, defaults)

    async def test_subnet_scan_form_prefills_current_local_subnet(self) -> None:
        self.config_flow.local_ipv4_addresses_from_hass = lambda _hass: [
            "192.168.2.147"
        ]

        result = await self.flow.async_step_user(
            {self.config_flow.CONF_SCAN_AUTOMATICALLY: True}
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "subnet_scan")
        defaults = {}
        suggested_values = {}
        for marker in result["data_schema"].schema:
            key = getattr(marker, "key", getattr(marker, "schema", None))
            default = getattr(marker, "default", None)
            if callable(default):
                default = default()
            defaults[key] = default
            description = getattr(marker, "description", None) or {}
            if "suggested_value" in description:
                suggested_values[key] = description["suggested_value"]
        self.assertEqual(
            suggested_values[self.config_flow.CONF_SCAN_NETWORK_ADDRESS],
            "192.168.2.0",
        )
        self.assertEqual(
            suggested_values[self.config_flow.CONF_SCAN_NETMASK],
            "255.255.255.0",
        )
        self.assertEqual(suggested_values[self.config_flow.CONF_SCAN_CIDR], "")
        self.assertEqual(result["data_schema"]({}), {})
        self.assertEqual(
            result["data_schema"](
                {
                    self.config_flow.CONF_SCAN_NETWORK_ADDRESS: "",
                    self.config_flow.CONF_SCAN_NETMASK: "",
                    self.config_flow.CONF_SCAN_CIDR: "192.168.2.0/25",
                }
            ),
            {
                self.config_flow.CONF_SCAN_NETWORK_ADDRESS: "",
                self.config_flow.CONF_SCAN_NETMASK: "",
                self.config_flow.CONF_SCAN_CIDR: "192.168.2.0/25",
            },
        )

    async def test_user_step_manual_choice_shows_manual_form_without_scan(self) -> None:
        self.config_flow.async_scan_dhe_hosts = AsyncMock(return_value=[])

        result = await self.flow.async_step_user(
            {self.config_flow.CONF_SCAN_AUTOMATICALLY: False}
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
            {self.config_flow.CONF_SCAN_AUTOMATICALLY: True}
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "subnet_scan")
        result = await self.flow.async_step_subnet_scan(
            {
                self.config_flow.CONF_SCAN_NETWORK_ADDRESS: "192.168.2.0",
                self.config_flow.CONF_SCAN_NETMASK: "255.255.255.0",
                self.config_flow.CONF_SCAN_CIDR: "",
            }
        )

        self.assertEqual(result["type"], "progress")
        await self._tasks[0]
        self.config_flow.async_scan_dhe_hosts.assert_awaited_once_with(
            self.flow.hass,
            networks=[ip_network("192.168.2.0/24")],
        )

    async def test_user_step_scan_uses_cidr_subnet(self) -> None:
        self.config_flow.async_scan_dhe_hosts = AsyncMock(return_value=[])

        result = await self.flow.async_step_user(
            {self.config_flow.CONF_SCAN_AUTOMATICALLY: True}
        )

        self.assertEqual(result["step_id"], "subnet_scan")
        result = await self.flow.async_step_subnet_scan(
            {
                self.config_flow.CONF_SCAN_NETWORK_ADDRESS: "",
                self.config_flow.CONF_SCAN_NETMASK: "",
                self.config_flow.CONF_SCAN_CIDR: "192.168.2.0/25",
            }
        )

        self.assertEqual(result["type"], "progress")
        await self._tasks[0]
        self.config_flow.async_scan_dhe_hosts.assert_awaited_once_with(
            self.flow.hass,
            networks=[ip_network("192.168.2.0/25")],
        )

    async def test_user_step_scan_rejects_mixed_subnet_alternatives(self) -> None:
        self.config_flow.async_scan_dhe_hosts = AsyncMock(return_value=[])

        await self.flow.async_step_user(
            {self.config_flow.CONF_SCAN_AUTOMATICALLY: True}
        )
        result = await self.flow.async_step_subnet_scan(
            {
                self.config_flow.CONF_SCAN_NETWORK_ADDRESS: "192.168.2.0",
                self.config_flow.CONF_SCAN_NETMASK: "255.255.255.0",
                self.config_flow.CONF_SCAN_CIDR: "192.168.2.0/24",
            }
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "subnet_scan")
        self.assertEqual(
            result["errors"][self.config_flow.CONF_SCAN_CIDR],
            "invalid_scan_subnet",
        )
        self.config_flow.async_scan_dhe_hosts.assert_not_called()

    async def test_user_step_scan_rejects_invalid_subnet(self) -> None:
        self.config_flow.async_scan_dhe_hosts = AsyncMock(return_value=[])

        result = await self.flow.async_step_user(
            {self.config_flow.CONF_SCAN_AUTOMATICALLY: True}
        )

        self.assertEqual(result["step_id"], "subnet_scan")
        result = await self.flow.async_step_subnet_scan(
            {
                self.config_flow.CONF_SCAN_NETWORK_ADDRESS: "192.168.0.0",
                self.config_flow.CONF_SCAN_NETMASK: "255.255.0.0",
                self.config_flow.CONF_SCAN_CIDR: "",
            }
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "subnet_scan")
        self.assertEqual(
            result["errors"][self.config_flow.CONF_SCAN_NETMASK],
            "scan_subnet_too_large",
        )
        self.config_flow.async_scan_dhe_hosts.assert_not_called()

    async def test_user_step_scan_rejects_wildcard_netmask(self) -> None:
        self.config_flow.async_scan_dhe_hosts = AsyncMock(return_value=[])

        result = await self.flow.async_step_user(
            {self.config_flow.CONF_SCAN_AUTOMATICALLY: True}
        )

        self.assertEqual(result["step_id"], "subnet_scan")
        result = await self.flow.async_step_subnet_scan(
            {
                self.config_flow.CONF_SCAN_NETWORK_ADDRESS: "192.168.2.0",
                self.config_flow.CONF_SCAN_NETMASK: "0.0.0.255",
                self.config_flow.CONF_SCAN_CIDR: "",
            }
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "subnet_scan")
        self.assertEqual(
            result["errors"][self.config_flow.CONF_SCAN_NETMASK],
            "invalid_scan_subnet",
        )
        self.config_flow.async_scan_dhe_hosts.assert_not_called()

    async def test_user_step_scan_rejects_slash_wildcard_netmask(self) -> None:
        self.config_flow.async_scan_dhe_hosts = AsyncMock(return_value=[])

        result = await self.flow.async_step_user(
            {self.config_flow.CONF_SCAN_AUTOMATICALLY: True}
        )

        self.assertEqual(result["step_id"], "subnet_scan")
        result = await self.flow.async_step_subnet_scan(
            {
                self.config_flow.CONF_SCAN_NETWORK_ADDRESS: "",
                self.config_flow.CONF_SCAN_NETMASK: "",
                self.config_flow.CONF_SCAN_CIDR: "192.168.2.0/0.0.0.255",
            }
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "subnet_scan")
        self.assertEqual(
            result["errors"][self.config_flow.CONF_SCAN_CIDR],
            "invalid_scan_subnet",
        )
        self.config_flow.async_scan_dhe_hosts.assert_not_called()

    async def test_user_step_runs_scan_then_prefills_manual_form(self) -> None:
        self.config_flow.async_scan_dhe_hosts = AsyncMock(
            return_value=[
                self.config_flow.DHEHostCandidate(
                    "192.0.2.124",
                    8443,
                    ("STE DHE App",),
                )
            ]
        )

        result = await self.flow.async_step_user(
            {self.config_flow.CONF_SCAN_AUTOMATICALLY: True}
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "subnet_scan")
        result = await self.flow.async_step_subnet_scan({})

        self.assertEqual(result["type"], "progress")
        self.assertEqual(result["step_id"], "network_scan")
        self.assertEqual(result["progress_action"], "scan_dhe")
        await self._tasks[0]

        result = await self.flow.async_step_network_scan({})

        self.assertEqual(result["type"], "progress_done")

        result = await self.flow.async_step_manual()

        defaults = {}
        for marker in result["data_schema"].schema:
            key = getattr(marker, "key", getattr(marker, "schema", None))
            default = getattr(marker, "default", None)
            if callable(default):
                default = default()
            defaults[key] = default
        self.assertEqual(defaults[self.config_flow.CONF_HOST], "192.0.2.124")
        self.assertEqual(defaults[self.config_flow.CONF_PORT], 8443)
        self.assertIn("Found one DHE", result["description_placeholders"]["scan_status"])

    async def test_user_step_falls_back_to_manual_form_when_scan_finds_nothing(
        self,
    ) -> None:
        self.config_flow.async_scan_dhe_hosts = AsyncMock(return_value=[])

        result = await self.flow.async_step_user(
            {self.config_flow.CONF_SCAN_AUTOMATICALLY: True}
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "subnet_scan")
        result = await self.flow.async_step_subnet_scan({})

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

        self.assertEqual(result, "requesting_token: websocket closed")
