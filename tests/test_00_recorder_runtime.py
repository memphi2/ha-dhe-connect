"""Verify real SQLite recorder rows, not just entity write mocks."""

from __future__ import annotations

import asyncio
import importlib
import json
import sqlite3
from contextlib import asynccontextmanager, closing
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant import loader
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.tasks import (
    PurgeTask,
    StatisticsTask,
    SynchronizeTask,
)
from homeassistant.helpers import entity_platform, entity_registry
from homeassistant.helpers.recorder import async_initialize_recorder
from homeassistant.setup import async_setup_component
from sqlalchemy import event

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
            yield SimpleNamespace(hass=hass, client=client, protocol=protocol, entities=entities,
                                  rows=rows, database=database)
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


async def test_retention_bounds_history_without_losing_consumption_statistics(tmp_path):
    """Accelerate event time, not HA's scheduler; exercise real purge and VACUUM."""
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    timestamp = start.timestamp() + 1
    clock = SimpleNamespace(time=lambda: timestamp)
    with (
        patch("homeassistant.core.time", clock),
        patch("homeassistant.helpers.entity.timer", side_effect=clock.time),
    ):
        async with recording_integration(tmp_path) as runtime:
            hass, client, protocol = runtime.hass, runtime.client, runtime.protocol
            recorder = get_instance(hass)
            await recorder.async_block_till_done()
            entity_ids = tuple(runtime.entities[key].entity_id for key in (
                "energy_consumption_total", "water_consumption_total",
            ))
            vacuum_done = asyncio.Event()

            def note_vacuum(_conn, _cursor, statement, _parameters, _context, _many):
                if statement.strip().upper() == "VACUUM":
                    hass.loop.call_soon_threadsafe(vacuum_done.set)

            event.listen(recorder.engine, "after_cursor_execute", note_vacuum)

            async def committed():
                future = hass.loop.create_future()
                recorder.queue_task(SynchronizeTask(future))
                await asyncio.wait_for(future, 15)

            def read_retention():
                with closing(sqlite3.connect(runtime.database)) as connection:
                    assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                    assert connection.execute("PRAGMA freelist_count").fetchone() == (0,)
                    history = connection.execute(
                        "SELECT COUNT(*), MIN(s.last_updated_ts) FROM states s "
                        "JOIN states_meta m ON m.metadata_id=s.metadata_id "
                        "WHERE m.entity_id IN (?, ?)", entity_ids,
                    ).fetchone()
                    short_term = connection.execute(
                        "SELECT COUNT(*), MIN(s.start_ts) FROM statistics_short_term s "
                        "JOIN statistics_meta m ON m.id=s.metadata_id "
                        "WHERE m.statistic_id IN (?, ?)", entity_ids,
                    ).fetchone()
                    totals = connection.execute(
                        "SELECT m.statistic_id, s.start_ts, s.sum FROM statistics s "
                        "JOIN statistics_meta m ON m.id=s.metadata_id "
                        "WHERE m.statistic_id IN (?, ?) ORDER BY m.statistic_id, s.start_ts",
                        entity_ids,
                    ).fetchall()
                    return history, short_term, totals

            retained_counts = []
            try:
                for day in range(6):
                    period = start + timedelta(days=day)
                    for sample in range(120):
                        timestamp = period.timestamp() + sample * 30 + 1
                        value = 100 + (day * 120 + sample) / 10
                        client.emit_measurement(protocol.ID_ENERGY_CONSUMPTION_YEARS, value)
                        client.emit_measurement(protocol.ID_WATER_CONSUMPTION_YEARS, value)
                        await hass.async_block_till_done()
                    await committed()
                    for minute in range(0, 60, 5):
                        recorder.queue_task(StatisticsTask(period + timedelta(minutes=minute), False))
                    await committed()
                    if day < 2:
                        continue
                    cutoff = period - timedelta(days=1)
                    vacuum_done.clear()
                    recorder.queue_task(PurgeTask(cutoff, repack=True, apply_filter=False))
                    await asyncio.wait_for(vacuum_done.wait(), 15)
                    await committed()
                    history, short_term, totals = await hass.async_add_executor_job(read_retention)
                    for count, oldest in (history, short_term):
                        assert count > 0
                        assert oldest >= cutoff.timestamp()
                    retained_counts.append((history[0], short_term[0]))
                    for entity_id in entity_ids:
                        series = [(timestamp, total) for key, timestamp, total in totals if key == entity_id]
                        assert len(series) == day + 1
                        assert series[0][0] == start.timestamp()
                        assert [total for _, total in series] == pytest.approx([
                            (index * 120 + 119) / 10 for index in range(day + 1)
                        ])
                assert len(retained_counts) == 4
                assert len(set(retained_counts)) == 1
            finally:
                event.remove(recorder.engine, "after_cursor_execute", note_vacuum)
