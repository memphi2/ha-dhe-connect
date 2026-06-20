"""Tests for DHE client exception classification helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMPONENT_DIR = ROOT / "custom_components" / "stiebel_dhe_connect"
PACKAGE_NAME = "custom_components.stiebel_dhe_connect"

try:
    from tests.test_aiohttp_stubs import _ensure_aiohttp_stub
except ModuleNotFoundError:
    from test_aiohttp_stubs import _ensure_aiohttp_stub


def _load_component_module(module_name: str):
    _ensure_aiohttp_stub()
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


def _load_client_errors():
    _load_component_module("client_types")
    return _load_component_module("client_errors")


class TestClientErrors(unittest.TestCase):
    """Validate transport/runtime exception classification."""

    def setUp(self) -> None:
        self.errors = _load_client_errors()

    def test_transport_exception_tuple_excludes_runtime_error(self) -> None:
        self.assertNotIn(RuntimeError, self.errors.DHE_TRANSPORT_EXCEPTIONS)

    def test_runtime_transport_error_or_raise_accepts_shutdown_races(self) -> None:
        messages = (
            "Cannot write to closing transport",
            "Connection reset by peer",
            "Session is closed",
            "socket closing",
            "socket write failed",
            "transport lost",
            "websocket connection is closed",
        )

        for message in messages:
            with self.subTest(message=message):
                error = RuntimeError(message)

                self.assertIs(self.errors.runtime_transport_error_or_raise(error), error)

    def test_runtime_transport_error_or_raise_rejects_programming_errors(self) -> None:
        messages = (
            "unexpected invalid state",
            "socket handler entered invalid state",
            "transport parser invariant failed",
        )

        for message in messages:
            with self.subTest(message=message), self.assertRaisesRegex(
                RuntimeError, message
            ):
                self.errors.runtime_transport_error_or_raise(RuntimeError(message))

    def test_suppress_transport_errors_preserves_programming_runtime_errors(self) -> None:
        with self.errors.suppress_transport_errors():
            raise RuntimeError("socket closed")

        with self.assertRaisesRegex(
            RuntimeError, "unexpected invalid state"
        ), self.errors.suppress_transport_errors():
            raise RuntimeError("unexpected invalid state")


if __name__ == "__main__":
    unittest.main()
