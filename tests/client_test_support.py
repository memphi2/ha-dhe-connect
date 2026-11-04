"""Shared stub-compatible module loaders for DHE client tests."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT_DIR = ROOT / "custom_components" / "stiebel_dhe_connect"
PACKAGE_NAME = "custom_components.stiebel_dhe_connect"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from tests.test_aiohttp_stubs import _ensure_aiohttp_stub
except ModuleNotFoundError:
    from test_aiohttp_stubs import _ensure_aiohttp_stub


def _load_component_module(module_name: str):
    _ensure_aiohttp_stub()
    try:
        from tests.test_ha_stubs import ensure_homeassistant_stubs
    except ModuleNotFoundError:
        from test_ha_stubs import ensure_homeassistant_stubs

    ensure_homeassistant_stubs()
    root_module_name = "custom_components"
    if root_module_name not in sys.modules:
        root_module = types.ModuleType(root_module_name)
        root_module.__path__ = [str(ROOT / root_module_name)]
        sys.modules[root_module_name] = root_module

    package = sys.modules.get(PACKAGE_NAME)
    if package is None:
        package = types.ModuleType(PACKAGE_NAME)
        package.__path__ = [str(COMPONENT_DIR)]
        package.__package__ = root_module_name
        sys.modules[PACKAGE_NAME] = package

    module_filename = COMPONENT_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE_NAME}.{module_name}",
        module_filename,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[f"{PACKAGE_NAME}.{module_name}"] = module
    spec.loader.exec_module(module)
    return module


def _load_client():
    _load_component_module("client_types")
    _load_component_module("client_mapping")
    _load_component_module("client_diagnostics")
    _load_component_module("client_errors")
    _load_component_module("client_constants")
    _load_component_module("connection_helpers")
    _load_component_module("engineio_helpers")
    _load_component_module("flow_helpers")
    _load_component_module("pairing_helpers")
    _load_component_module("protocol")
    _load_component_module("client_value_helpers")
    _load_component_module("device_info_helpers")
    _load_component_module("client_connection_supervisor")
    _load_component_module("client_callbacks")
    _load_component_module("client_connection_state")
    _load_component_module("client_pairing")
    _load_component_module("client_command_runner")
    _load_component_module("client_device_info_commands")
    _load_component_module("client_radio_commands")
    _load_component_module("client_weather_commands")
    _load_component_module("client_temperature_memory_commands")
    _load_component_module("client_wellness_timer_commands")
    _load_component_module("client_commands")
    _load_component_module("client_runtime_app")
    _load_component_module("client_runtime_media")
    _load_component_module("client_runtime")
    _load_component_module("http_helpers")
    _load_component_module("client_web_version")
    _load_component_module("token_storage")
    _load_component_module("client_transport_helpers")
    _load_component_module("client_transport_auth")
    _load_component_module("client_transport")
    return _load_component_module("client")


def _load_protocol():
    return _load_component_module("protocol")
