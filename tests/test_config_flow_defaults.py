"""Tests for config flow device settings defaults."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FLOW_PATH = (
    ROOT / "custom_components" / "stiebel_dhe_connect" / "config_flow.py"
)
PACKAGE_ROOT = ROOT / "custom_components"
MODULE_NAME = "custom_components.stiebel_dhe_connect.config_flow"


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
    fake_connection.should_check_connectivity = lambda *_args, **_kwargs: False
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
    fake_pairing.map_pairing_error = lambda error: str(error)
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


class TestDeviceSettingsDefaults(unittest.TestCase):
    """Validate currency fallbacks for device settings defaults."""

    def setUp(self) -> None:
        self.config_flow = _load_config_flow()

    def test_device_settings_defaults_uses_device_currency_when_available(self) -> None:
        class Client:
            last_measurements = {self.config_flow.ID_APP_CURRENCY: "gbp"}

        defaults = self.config_flow._device_settings_defaults(Client())

        self.assertEqual(defaults[self.config_flow.ATTR_CURRENCY], "GBP")

    def test_device_settings_defaults_uses_unchanged_when_currency_missing(self) -> None:
        class Client:
            last_measurements = {}

        defaults = self.config_flow._device_settings_defaults(Client())

        self.assertEqual(
            defaults[self.config_flow.ATTR_CURRENCY],
            self.config_flow.CURRENCY_UNCHANGED,
        )

    def test_device_settings_defaults_uses_unchanged_when_currency_is_unset(self) -> None:
        class Client:
            last_measurements = {self.config_flow.ID_APP_CURRENCY: "UNSET"}

        defaults = self.config_flow._device_settings_defaults(Client())

        self.assertEqual(
            defaults[self.config_flow.ATTR_CURRENCY],
            self.config_flow.CURRENCY_UNCHANGED,
        )

    def test_device_settings_defaults_uses_unchanged_when_currency_not_supported(self) -> None:
        class Client:
            last_measurements = {self.config_flow.ID_APP_CURRENCY: "JPY"}

        defaults = self.config_flow._device_settings_defaults(Client())

        self.assertEqual(
            defaults[self.config_flow.ATTR_CURRENCY],
            self.config_flow.CURRENCY_UNCHANGED,
        )
