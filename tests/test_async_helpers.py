"""Tests for shared async helpers."""

from __future__ import annotations

import asyncio
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock

from homeassistant.core import HomeAssistant

ROOT = Path(__file__).resolve().parents[1]
ASYNC_HELPERS = ROOT / "custom_components" / "stiebel_dhe_connect" / "async_helpers.py"


def _load_async_helpers():
    spec = importlib.util.spec_from_file_location("async_helpers", ASYNC_HELPERS)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAsyncHelpers(unittest.IsolatedAsyncioTestCase):
    """Validate async task lifecycle helpers."""

    def setUp(self) -> None:
        self.helpers = _load_async_helpers()

    async def test_background_task_uses_ha_background_api_and_preserves_result(self) -> None:
        hass = Mock(spec=HomeAssistant)
        hass.async_create_background_task.side_effect = (
            lambda coro, name: asyncio.create_task(coro, name=name)
        )

        async def _work() -> str:
            return "done"

        coro = _work()
        task = self.helpers.create_background_task(hass, coro, "dhe-test-background")

        self.assertEqual(await task, "done")
        self.assertEqual(task.get_name(), "dhe-test-background")
        hass.async_create_background_task.assert_called_once_with(coro, "dhe-test-background")
        hass.async_create_task.assert_not_called()

    async def test_cancel_task_if_pending_cancels_and_awaits_task(self) -> None:
        started = asyncio.Event()

        async def _pending() -> None:
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(_pending())
        await started.wait()

        await self.helpers.cancel_task_if_pending(task)

        self.assertTrue(task.cancelled())

    async def test_cancel_task_if_pending_ignores_finished_task(self) -> None:
        async def _done() -> str:
            return "ok"

        task = asyncio.create_task(_done())
        self.assertEqual(await task, "ok")

        await self.helpers.cancel_task_if_pending(task)

        self.assertTrue(task.done())
        self.assertFalse(task.cancelled())


if __name__ == "__main__":
    unittest.main()
