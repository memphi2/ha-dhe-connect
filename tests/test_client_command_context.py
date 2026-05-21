"""Tests for DHE client mixin typing-context helpers."""

from __future__ import annotations

try:
    from tests.test_client_weather_favorites import _load_component_module
except ModuleNotFoundError:
    from test_client_weather_favorites import _load_component_module


def test_client_context_helpers_are_runtime_noops() -> None:
    """Context helpers should only narrow types for mypy, not wrap clients."""
    context_module = _load_component_module("client_command_context")
    client = object()

    assert context_module.command_context(client) is client
    assert context_module.connection_context(client) is client
    assert context_module.diagnostics_context(client) is client
    assert context_module.runtime_context(client) is client
    assert context_module.transport_context(client) is client
