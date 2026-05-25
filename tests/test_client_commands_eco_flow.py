"""Tests for eco flow limit command normalization."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = ROOT / "custom_components" / "stiebel_dhe_connect"


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestClientCommandsEcoFlow(unittest.IsolatedAsyncioTestCase):
    """Verify eco flow limit values are normalized to supported writes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.protocol = _load_module(
            "custom_components.stiebel_dhe_connect.protocol",
            MODULE_DIR / "protocol.py",
        )
        cls.client_commands = _load_module(
            "custom_components.stiebel_dhe_connect.client_commands",
            MODULE_DIR / "client_commands.py",
        )

    async def test_set_eco_flow_limit_rounds_half_up_and_writes_raw_tenths(self) -> None:
        client = types.SimpleNamespace(write_odb_value=AsyncMock(return_value=9.0))

        result = await self.client_commands.DHEClientCommandsMixin.set_eco_flow_limit(
            client, 8.5
        )

        self.assertEqual(result, 9.0)
        client.write_odb_value.assert_awaited_once_with(
            self.protocol.ID_ECO_FLOW_LIMIT,
            90,
        )

    async def test_set_eco_flow_limit_clamps_to_allowed_range(self) -> None:
        low_client = types.SimpleNamespace(write_odb_value=AsyncMock(return_value=4.0))
        high_client = types.SimpleNamespace(write_odb_value=AsyncMock(return_value=15.0))

        await self.client_commands.DHEClientCommandsMixin.set_eco_flow_limit(
            low_client,
            3.2,
        )
        await self.client_commands.DHEClientCommandsMixin.set_eco_flow_limit(
            high_client,
            15.9,
        )

        low_client.write_odb_value.assert_awaited_once_with(
            self.protocol.ID_ECO_FLOW_LIMIT,
            40,
        )
        high_client.write_odb_value.assert_awaited_once_with(
            self.protocol.ID_ECO_FLOW_LIMIT,
            150,
        )


if __name__ == "__main__":
    unittest.main()
