"""Bounded lifecycle/reconnect/idle measurements with real HA and loopback I/O."""

from __future__ import annotations

import asyncio
import gc
import importlib
import json
import logging
import os
import tracemalloc
import weakref
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import loader

from scripts.check_runtime_soak import LIMITS, PHASES, sample_errors

try:
    from tests.test_00_ha_fixture_runtime import (
        DOMAIN,
        _async_test_home_assistant,
        _build_mock_entry,
        _clear_loaded_integration_modules,
        _ensure_network_loaded,
    )
    from tests.test_fake_dhe_engineio_server import (
        STORED_TOKEN,
        FakeDHEEngineIOServer,
        _decode_length_prefixed_packets,
    )
except ModuleNotFoundError:
    from test_00_ha_fixture_runtime import (
        DOMAIN,
        _async_test_home_assistant,
        _build_mock_entry,
        _clear_loaded_integration_modules,
        _ensure_network_loaded,
    )
    from test_fake_dhe_engineio_server import (
        STORED_TOKEN,
        FakeDHEEngineIOServer,
        _decode_length_prefixed_packets,
    )


def _callback_count(client) -> int:
    return sum(
        len(value)
        for name, value in vars(client).items()
        if name.endswith("_callbacks") and isinstance(value, set)
    )


def _snapshot(phase, client, references):
    gc.collect()
    tasks = [task for task in asyncio.all_tasks() if not task.done()]
    owned_tasks = sum(
        "stiebel_dhe_connect" in task.get_name()
        or "stiebel_dhe_connect"
        in getattr(getattr(task.get_coro(), "cr_code", None), "co_filename", "")
        for task in tasks
    )
    snapshot = tracemalloc.take_snapshot()
    integration_bytes = sum(
        stat.size
        for stat in snapshot.statistics("filename")
        if "/custom_components/stiebel_dhe_connect/" in stat.traceback[0].filename
    )
    del snapshot
    try:
        rss_bytes = int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf(
            "SC_PAGE_SIZE"
        )
    except (OSError, ValueError, IndexError, AttributeError):
        rss_bytes = None
    return {
        "phase": phase,
        "tasks": len(tasks),
        "owned_tasks": owned_tasks,
        "scheduled_handles": sum(
            not handle.cancelled() for handle in asyncio.get_running_loop()._scheduled
        ),
        "callbacks": _callback_count(client) if client is not None else 0,
        "retained_clients": sum(reference() is not None for reference in references),
        "integration_bytes": integration_bytes,
        "traced_bytes": tracemalloc.get_traced_memory()[0],
        "rss_bytes": rss_bytes,
    }


async def _wait_connected(client, previous_ctx=None):
    try:
        async with asyncio.timeout(10):
            while (
                client.diagnostic_state["connection_state"] != "connected"
                or client._ctx is previous_ctx
            ):
                await asyncio.sleep(0.01)
    except TimeoutError:
        pytest.fail(f"Fake transport did not connect: {client.diagnostic_state}")


def _queue_startup(server, protocol):
    server.queue_authentication()
    server.queue_event(
        "message",
        {
            "command": protocol.ODB_SET_COMMAND,
            "value": {"id": protocol.ID_DEVICE_STATUS, "value": 1},
        },
    )


class _SoakServer(FakeDHEEngineIOServer):
    """Answer the current session, not a future session's prequeued handshake."""

    async def _handle_post(self, request):
        body = await request.text()
        response = await super()._handle_post(request)
        for packet in _decode_length_prefixed_packets(body):
            if not packet.startswith("42") or "[" not in packet:
                continue
            event = json.loads(packet[packet.index("[") :])
            if event[0] == "token_request":
                protocol = importlib.import_module(
                    f"custom_components.{DOMAIN}.protocol"
                )
                _queue_startup(self, protocol)
        return response


def _trim_server_history(server):
    server.posted_packets.clear()
    server.websocket_packets.clear()
    server.websockets[:] = [socket for socket in server.websockets if not socket.closed]


@pytest.mark.asyncio
async def test_runtime_soak(caplog):
    """Measure both complete lifecycles and repeated reconnects on one client."""
    cycles = int(os.environ.get("DHE_SOAK_CYCLES", "3"))
    idle_seconds = float(os.environ.get("DHE_SOAK_IDLE_SECONDS", "0.5"))
    # Pytest's log history must not become the measured source of retention.
    caplog.set_level(logging.CRITICAL)
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    protocol = importlib.import_module(f"custom_components.{DOMAIN}.protocol")
    supervisor = importlib.import_module(
        f"custom_components.{DOMAIN}.client_connection_supervisor"
    )
    samples, references = [], []
    was_tracing = tracemalloc.is_tracing()
    if not was_tracing:
        tracemalloc.start()
    try:
        async with _async_test_home_assistant() as hass:
            hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
            await _ensure_network_loaded(hass)
            async with _SoakServer(protocol.NS) as server:
                entry = _build_mock_entry(
                    host=server.host,
                    port=server.port,
                    name="Soak DHE",
                    unique_id="soak-dhe",
                )
                entry.add_to_hass(hass)
                hass.config_entries.async_update_entry(
                    entry, data={**entry.data, "token": STORED_TOKEN}
                )
                with patch.object(
                    integration, "_async_can_connect", AsyncMock(return_value=True)
                ):
                    for cycle in range(cycles + 2):
                        assert await hass.config_entries.async_setup(entry.entry_id)
                        client = entry.runtime_data.client
                        references.append(weakref.ref(client))
                        # Only the delay policy is accelerated; transport/lifecycle stay real.
                        client._connection_supervisor = (
                            supervisor.DHEConnectionSupervisor(
                                base_delay=0.01, max_delay=0.02, grace_period=0.1
                            )
                        )
                        await _wait_connected(client)
                        await hass.async_block_till_done()
                        assert client._ctx.websocket is not None
                        assert _callback_count(client) > 0
                        assert hass.states.get("climate.soak_dhe_water_heating") is not None
                        _trim_server_history(server)
                        if cycle >= 2:
                            samples.append(
                                _snapshot("connected", client, references[:-1])
                            )
                        previous_ctx = client._ctx
                        await server.close_active_websockets()
                        await _wait_connected(client, previous_ctx)
                        del previous_ctx
                        await hass.async_block_till_done()
                        _trim_server_history(server)
                        if cycle >= 2:
                            samples.append(
                                _snapshot("reconnected", client, references[:-1])
                            )
                        if cycle == cycles + 1:
                            for reconnect in range(cycles + 2):
                                previous_ctx = client._ctx
                                await server.close_active_websockets()
                                await _wait_connected(client, previous_ctx)
                                del previous_ctx
                                await hass.async_block_till_done()
                                assert entry.runtime_data.client is client
                                _trim_server_history(server)
                                if reconnect >= 2:
                                    samples.append(_snapshot(
                                        "same_client_reconnected", client, references[:-1]
                                    ))
                            deadline = hass.loop.time() + idle_seconds
                            while True:
                                _trim_server_history(server)
                                samples.append(
                                    _snapshot("idle", client, references[:-1])
                                )
                                remaining = deadline - hass.loop.time()
                                if remaining <= 0:
                                    break
                                await asyncio.sleep(min(1.0, remaining))
                            assert (
                                client.diagnostic_state["connection_state"]
                                == "connected"
                            )
                        assert await hass.config_entries.async_unload(entry.entry_id)
                        await hass.async_block_till_done()
                        assert _callback_count(client) == 0
                        assert client._runner is None and client._ctx is None
                        del client
                        await asyncio.sleep(0)
                        _trim_server_history(server)
                        if cycle >= 2:
                            samples.append(_snapshot("unloaded", None, references))
        errors = sample_errors(samples)
        report = {
            "cycles": cycles,
            "warmup_cycles": 2,
            "same_client_reconnects": cycles + 2,
            "idle_seconds": idle_seconds,
            "limits": LIMITS,
            "errors": errors,
            "ranges": {
                phase: {
                    metric: [min(values), max(values)]
                    for metric in LIMITS
                    if (
                        values := [
                            sample[metric]
                            for sample in samples
                            if sample["phase"] == phase and sample[metric] is not None
                        ]
                    )
                }
                for phase in PHASES
            },
            "samples": samples,
        }
        if report_path := os.environ.get("DHE_SOAK_REPORT"):
            Path(report_path).write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
        assert not errors, errors
    finally:
        if not was_tracing:
            tracemalloc.stop()
