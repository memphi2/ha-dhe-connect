"""Tests for shared async helpers."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import unittest


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
