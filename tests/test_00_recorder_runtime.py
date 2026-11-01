"""Verify real SQLite recorder rows, not just entity write mocks."""

from __future__ import annotations

import asyncio
import importlib
import json
import sqlite3
from contextlib import asynccontextmanager, closing
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant import loader
from homeassistant.helpers import entity_platform, entity_registry
from homeassistant.helpers.recorder import async_initialize_recorder
from homeassistant.setup import async_setup_component

from tests.ha_test_support import (
    DOMAIN,
    _async_test_home_assistant,
    _build_mock_entry,
    _clear_loaded_integration_modules,
    _FixtureDHEClient,
)

pytestmark = pytest.mark.asyncio
recorder_helpers = importlib.import_module(
    ("pytest_homeassistant" if importlib.util.find_spec("pytest_homeassistant")
     else "pytest_homeassistant_custom_component") + ".components.recorder.common"
)


@asynccontextmanager
async def recording_integration(tmp_path, *, timer=False):
    _clear_loaded_integration_modules()
    integration = importlib.import_module(f"custom_components.{DOMAIN}")
    protocol = importlib.import_module(f"custom_components.{DOMAIN}.protocol")
    database = tmp_path / "recorder.db"
    async with _async_test_home_assistant() as hass:
        async_initialize_recorder(hass)
        assert await async_setup_component(hass, "recorder", {"recorder": {
            "db_url": f"sqlite:///{database}", "auto_purge": False, "commit_interval": 0,
        }})
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        client = _FixtureDHEClient()
        entry = _build_mock_entry(host=client.host, port=client.port, name="Recorder DHE", unique_id="recorder-dhe")
        entry.add_to_hass(hass)
        if timer:
            entity_registry.async_get(hass).async_get_or_create(
                "sensor", DOMAIN, f"{DOMAIN}_{entry.entry_id}_shower_timer_remaining",
                config_entry=entry, disabled_by=None,
            )
        with (
            patch.object(integration, "DHEClient", return_value=client),
            patch.object(integration, "_async_can_connect", AsyncMock(return_value=True)),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
        entities = {
            entity.unique_id.removeprefix(f"{DOMAIN}_{entry.entry_id}_"): entity
            for platform in entity_platform.async_get_platforms(hass, DOMAIN)
            for entity in platform.entities.values()
        }

        async def rows(entity_id=None):
            await recorder_helpers.async_wait_recording_done(hass)

            def read_rows():
                with closing(sqlite3.connect(database)) as connection:
                    return connection.execute(
                        "SELECT m.entity_id, s.state, a.shared_attrs FROM states s "
                        "JOIN states_meta m ON s.metadata_id=m.metadata_id "
                        "LEFT JOIN state_attributes a ON s.attributes_id=a.attributes_id "
                        "WHERE (? IS NULL OR m.entity_id=?) ORDER BY s.state_id",
                        (entity_id, entity_id),
                    ).fetchall()
            return await hass.async_add_executor_job(read_rows)

        try:
            yield SimpleNamespace(hass=hass, client=client, protocol=protocol, entities=entities, rows=rows)
        finally:
            assert await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()


async def test_idle_and_jitter_have_bounded_recorder_rows(tmp_path):
    async with recording_integration(tmp_path) as runtime:
        client, protocol = runtime.client, runtime.protocol
        flow = runtime.entities["water_flow"]
        client.emit_measurement(protocol.ID_WATER_FLOW, 5.0)
        client.emit_diagnostic({"connection_state": "connected"})
        before = await runtime.rows()
        for index in range(500):
            client.emit_measurement(protocol.ID_WATER_FLOW, 5.0)
            client.emit_diagnostic({"connection_state": "connected", "message_count": index,
                                    "session_id": f"private-{index}", "websocket_sid": "private"})
        assert await runtime.rows() == before

        module = importlib.import_module(f"custom_components.{DOMAIN}.sensor")
        with patch.object(module, "async_call_later", return_value=Mock()) as schedule:
            for _ in range(500):
                client.emit_measurement(protocol.ID_WATER_FLOW, 5.1)
            assert await runtime.rows() == before
            schedule.assert_called_once()
            assert 0 <= schedule.call_args.args[1] <= 45
            schedule.call_args.args[2](None)
        assert len(await runtime.rows(flow.entity_id)) == len([r for r in before if r[0] == flow.entity_id]) + 1
        assert (await runtime.rows(flow.entity_id))[-1][1] == "5.1"

        for value in (0.0, 0.1, 0.0):
            previous = len(await runtime.rows(flow.entity_id))
            client.emit_measurement(protocol.ID_WATER_FLOW, value)
            assert len(await runtime.rows(flow.entity_id)) == previous + 1


async def test_live_catalog_updates_exclude_payloads_from_sqlite(tmp_path):
    async with recording_integration(tmp_path) as runtime:
        radio = runtime.entities["radio"]
        state = {"play": False, "volume": 30, "favorites": [{"Id": 1, "Name": "Station A"}]}
        radio._handle_radio_update(state)
        initial = await runtime.rows(radio.entity_id)
        state["favorites"][0]["Id"] = 2
        radio._handle_radio_update(state)
        assert runtime.hass.states.get(radio.entity_id).attributes["favorites"][0]["id"] == 2
        updated = await runtime.rows(radio.entity_id)
        assert len(updated) == len(initial) + 1
        for _, _, attributes in updated:
            assert "favorites" not in json.loads(attributes or "{}")
        radio._handle_radio_update(state)
        assert await runtime.rows(radio.entity_id) == updated

        client = runtime.client
        client.emit_weather({"location": {"Name": "Test", "LocationId": "ID=1"},
                             "favorites": [{"Name": "Test", "LocationId": "ID=1"}],
                             "forecast_results": [{"Name": "Candidate", "LocationId": "ID=2"}]})
        weather = runtime.entities["weather"]
        weather_rows = await runtime.rows(weather.entity_id)
        assert runtime.hass.states.get(weather.entity_id).attributes["forecast_results"]
        client.emit_weather({**client.last_weather_state,
                             "forecast_results": [{"Name": "Changed", "LocationId": "ID=3"}]})
        changed_rows = await runtime.rows(weather.entity_id)
        assert len(changed_rows) == len(weather_rows) + 1
        assert "Changed" in str(runtime.hass.states.get(weather.entity_id).attributes["forecast_results"])
        for _, _, attributes in changed_rows:
            recorded = json.loads(attributes or "{}")
            assert not {"favorite_locations", "forecast_results", "int_names"} & recorded.keys()


async def test_optional_countdown_records_only_while_running(tmp_path):
    async with recording_integration(tmp_path, timer=True) as runtime:
        sensor = runtime.entities["shower_timer_remaining"]
        sensor._timer_duration_minutes = lambda: 1.0
        sensor._timer_remaining_base_minutes = 0.0
        sensor._timer_active = False
        before = await runtime.rows(sensor.entity_id)
        await sensor._async_timer_countdown()
        assert await runtime.rows(sensor.entity_id) == before
        sensor._timer_active = True
        module = importlib.import_module(f"custom_components.{DOMAIN}.sensor")
        with patch.object(module, "TIMER_COUNTDOWN_INTERVAL_SECONDS", 0):
            await asyncio.wait_for(sensor._async_timer_countdown(), timeout=2)
        rows = await runtime.rows(sensor.entity_id)
        assert [row[1] for row in rows[len(before):]] == ["0:00", "1:00"]
        assert not sensor._timer_active
        await sensor._async_timer_countdown()
        assert await runtime.rows(sensor.entity_id) == rows
