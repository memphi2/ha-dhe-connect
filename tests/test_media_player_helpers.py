"""Tests for media-player helper behavior."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest

try:
    from tests.test_aiohttp_stubs import _ensure_aiohttp_stub
except ModuleNotFoundError:
    from test_aiohttp_stubs import _ensure_aiohttp_stub

ROOT = Path(__file__).resolve().parents[1]
COMPONENT_DIR = ROOT / "custom_components" / "stiebel_dhe_connect"
PACKAGE_NAME = "custom_components.stiebel_dhe_connect"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_additional_ha_stubs() -> None:
    from homeassistant.components import __dict__ as components_dict

    if "media_player" not in components_dict:
        media_player_module = types.ModuleType("homeassistant.components.media_player")

        class MediaPlayerEntity:
            pass

        class MediaPlayerEntityFeature(int):
            PLAY = 1
            PAUSE = 2
            TURN_ON = 4
            TURN_OFF = 8
            VOLUME_SET = 16
            SELECT_SOURCE = 32
            NEXT_TRACK = 64
            PREVIOUS_TRACK = 128

        class MediaPlayerState:
            IDLE = "idle"
            PAUSED = "paused"
            PLAYING = "playing"

        media_player_module.MediaPlayerEntity = MediaPlayerEntity
        media_player_module.MediaPlayerEntityFeature = MediaPlayerEntityFeature
        media_player_module.MediaPlayerState = MediaPlayerState
        sys.modules["homeassistant.components.media_player"] = media_player_module
        components_dict["media_player"] = media_player_module

    if "homeassistant.helpers.entity_platform" not in sys.modules:
        entity_platform_module = types.ModuleType("homeassistant.helpers.entity_platform")

        class AddEntitiesCallback:
            pass

        entity_platform_module.AddEntitiesCallback = AddEntitiesCallback
        sys.modules["homeassistant.helpers.entity_platform"] = entity_platform_module

    if "homeassistant.exceptions" not in sys.modules:
        exceptions_module = types.ModuleType("homeassistant.exceptions")

        class HomeAssistantError(Exception):
            pass

        exceptions_module.HomeAssistantError = HomeAssistantError
        sys.modules["homeassistant.exceptions"] = exceptions_module


def _load_component_module(module_name: str):
    _ensure_aiohttp_stub()
    try:
        from tests.test_ha_stubs import ensure_homeassistant_stubs
    except ModuleNotFoundError:
        from test_ha_stubs import ensure_homeassistant_stubs

    ensure_homeassistant_stubs()
    _ensure_additional_ha_stubs()

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


def _load_media_player_module():
    _load_component_module("client_mapping")
    _load_component_module("flow_helpers")
    _load_component_module("pairing_helpers")
    _load_component_module("protocol")
    _load_component_module("client")
    _load_component_module("entity_helpers")
    _load_component_module("entity_state_helpers")
    _load_component_module("radio_mapping")
    _load_component_module("runtime_helpers")
    return _load_component_module("media_player")


class TestMediaPlayerHelpers(unittest.TestCase):
    """Validate radio source helper behavior."""

    def test_current_source_index_matches_station_id(self) -> None:
        media_player = _load_media_player_module()
        player = media_player.StiebelDHERadioMediaPlayer.__new__(
            media_player.StiebelDHERadioMediaPlayer
        )
        player._attr_source = None
        player._attr_media_content_id = "2"
        player._sources_by_option = {
            "WDR 2 (1)": {"Id": 1, "Name": "WDR 2"},
            "WDR 2 (2)": {"Id": 2, "Name": "WDR 2"},
        }

        index = player._current_source_index(list(player._sources_by_option))

        self.assertEqual(index, 1)

    def test_current_source_index_prefers_selected_source(self) -> None:
        media_player = _load_media_player_module()
        player = media_player.StiebelDHERadioMediaPlayer.__new__(
            media_player.StiebelDHERadioMediaPlayer
        )
        player._attr_source = "WDR 2"
        player._attr_media_content_id = "999"
        player._sources_by_option = {
            "Radio Essen": {"Id": 971, "Name": "Radio Essen"},
            "WDR 2": {"Id": 3, "Name": "WDR 2"},
        }

        index = player._current_source_index(list(player._sources_by_option))

        self.assertEqual(index, 1)


if __name__ == "__main__":
    unittest.main()
