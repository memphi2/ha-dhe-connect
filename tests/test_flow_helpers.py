"""Tests for async flow helper utilities."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FLOW_HELPERS = ROOT / "custom_components" / "stiebel_dhe_connect" / "flow_helpers.py"


def _load_flow_helpers():
    spec = importlib.util.spec_from_file_location("flow_helpers", FLOW_HELPERS)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestFlowHelpers(unittest.IsolatedAsyncioTestCase):
    """Validate shared request/refresh flow helpers."""

    async def test_request_generation_and_wait_uses_captured_generation(self) -> None:
        module = _load_flow_helpers()
        trace: list[str] = []
        generation_value = 4

        async def request() -> None:
            trace.append("request")

        def generation_getter() -> int:
            trace.append("generation")
            return generation_value

        async def wait_for_generation(generation: int) -> int:
            trace.append(f"wait:{generation}")
            return generation + 1

        result = await module.request_generation_and_wait(
            request,
            generation_getter,
            wait_for_generation,
        )

        self.assertEqual(result, 5)
        self.assertEqual(trace, ["generation", "request", "wait:4"])

    async def test_wait_for_or_refresh_retries_after_retryable_error(self) -> None:
        module = _load_flow_helpers()
        trace: list[str] = []
        attempts = {"count": 0}

        async def wait() -> str:
            attempts["count"] += 1
            trace.append(f"wait:{attempts['count']}")
            if attempts["count"] == 1:
                raise ValueError("transient")
            return "ok"

        async def refresh() -> None:
            trace.append("refresh")

        result = await module.wait_for_or_refresh(
            wait,
            refresh,
            retry_exceptions=(ValueError,),
        )

        self.assertEqual(result, "ok")
        self.assertEqual(trace, ["wait:1", "refresh", "wait:2"])

    async def test_wait_for_or_refresh_does_not_swallow_other_errors(self) -> None:
        module = _load_flow_helpers()
        trace: list[str] = []

        async def wait() -> None:
            trace.append("wait")
            raise RuntimeError("fatal")

        async def refresh() -> None:
            trace.append("refresh")

        with self.assertRaises(RuntimeError):
            await module.wait_for_or_refresh(
                wait,
                refresh,
                retry_exceptions=(ValueError,),
            )

        self.assertEqual(trace, ["wait"])

    async def test_wait_until_returns_true_when_predicate_becomes_true(self) -> None:
        module = _load_flow_helpers()
        state = {"done": False}

        async def _flip() -> None:
            await asyncio.sleep(0.01)
            state["done"] = True

        asyncio.create_task(_flip())
        result = await module.wait_until(
            lambda: state["done"],
            timeout_seconds=0.2,
            poll_interval_seconds=0.005,
        )

        self.assertTrue(result)

    async def test_wait_until_returns_false_on_timeout(self) -> None:
        module = _load_flow_helpers()
        result = await module.wait_until(
            lambda: False,
            timeout_seconds=0.03,
            poll_interval_seconds=0.005,
        )
        self.assertFalse(result)

    async def test_wait_for_generation_change_returns_true_after_update(self) -> None:
        module = _load_flow_helpers()
        generation = {"value": 5}

        async def _bump() -> None:
            await asyncio.sleep(0.01)
            generation["value"] = 6

        asyncio.create_task(_bump())
        result = await module.wait_for_generation_change(
            5,
            lambda: generation["value"],
            timeout_seconds=0.2,
            poll_interval_seconds=0.005,
        )

        self.assertTrue(result)

    async def test_wait_for_generation_change_returns_false_on_timeout(self) -> None:
        module = _load_flow_helpers()
        result = await module.wait_for_generation_change(
            2,
            lambda: 2,
            timeout_seconds=0.03,
            poll_interval_seconds=0.005,
        )
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
