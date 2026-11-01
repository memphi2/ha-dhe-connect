"""Focused DHE client regression tests."""

from __future__ import annotations

import asyncio
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from tests.client_test_support import (
    PACKAGE_NAME,
    _load_client,
    _load_component_module,
    _load_protocol,
)


class TestClientCommands(unittest.IsolatedAsyncioTestCase):
    async def test_nonfinite_temperature_is_rejected_before_transport(self) -> None:
        module = _load_client()
        client = module.DHEClient.__new__(module.DHEClient)
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaisesRegex(module.DHEError, "finite"):
                await client.set_temperature(value)


    async def test_command_retry_recovers_from_runtime_transport_errors(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        for message in (
            "socket closing",
            "socket write failed",
            "Session is closed",
            "transport lost",
        ):
            with self.subTest(message=message):
                client = DHEClient.__new__(DHEClient)

                client._command_lock = asyncio.Lock()
                client._ctx = object()
                client._ensure_ready = AsyncMock()
                client._force_reconnect = AsyncMock()
                attempts = 0

                async def _operation(_ctx, message=message):
                    nonlocal attempts
                    attempts += 1
                    if attempts == 1:
                        raise RuntimeError(message)
                    return "ok"

                result = await DHEClient._run_command_with_reconnect_retry(
                    client,
                    "Could not run command",
                    _operation,
                )

                self.assertEqual(result, "ok")
                self.assertEqual(attempts, 2)
                self.assertEqual(client._ensure_ready.await_count, 2)
                client._force_reconnect.assert_awaited_once()


    async def test_command_retry_does_not_retry_programming_runtime_errors(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        client = DHEClient.__new__(DHEClient)

        client._command_lock = asyncio.Lock()
        client._ctx = object()
        client._ensure_ready = AsyncMock()
        client._force_reconnect = AsyncMock()

        for message in ("unexpected invalid state", "socket handler invalid state"):
            with self.subTest(message=message):
                client._ensure_ready.reset_mock()
                client._force_reconnect.reset_mock()

                async def _operation(_ctx, message=message):
                    raise RuntimeError(message)

                with self.assertRaisesRegex(RuntimeError, message):
                    await DHEClient._run_command_with_reconnect_retry(
                        client,
                        "Could not run command",
                        _operation,
                    )

                client._ensure_ready.assert_awaited_once()
                client._force_reconnect.assert_not_awaited()


    async def test_pairing_notification_ids_include_port(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        client_a = DHEClient.__new__(DHEClient)
        client_a.host = "dhe.local"
        client_a.port = 8443

        client_b = DHEClient.__new__(DHEClient)
        client_b.host = "dhe.local"
        client_b.port = 9443

        self.assertNotEqual(
            client_a._pairing_notification_id,
            client_b._pairing_notification_id,
        )
        self.assertNotEqual(
            client_a._pairing_confirmation_notification_id,
            client_b._pairing_confirmation_notification_id,
        )
        target_fragment = client_a._pairing_notification_id.rsplit("_", 1)[-1]
        self.assertNotIn("dhe", target_fragment)
        self.assertNotIn("local", target_fragment)
        self.assertNotIn("8443", target_fragment)


    async def test_notify_pairing_progress_replaces_scoped_pairing_notifications(
        self,
    ) -> None:
        client_module = _load_client()
        pairing_module = sys.modules[f"{PACKAGE_NAME}.client_pairing"]
        DHEClient = client_module.DHEClient

        class _FakeHass:
            pass

        client = DHEClient.__new__(DHEClient)
        client.hass = _FakeHass()
        client.host = "dhe.local"
        client.port = 9443

        client._pairing_notification_text = lambda _state: (
            "DHE Pairing",
            "waiting",
        )

        async_create = Mock()
        async_dismiss = Mock()

        pairing_module.persistent_notification.async_create = async_create
        pairing_module.persistent_notification.async_dismiss = async_dismiss

        client._notify_pairing_progress("connecting")

        self.assertEqual(async_dismiss.call_count, 2)
        async_dismiss.assert_any_call(
            client.hass,
            client._pairing_confirmation_notification_id,
        )
        async_dismiss.assert_any_call(
            client.hass,
            client._pairing_notification_id,
        )
        async_create.assert_called_once_with(
            client.hass,
            "waiting",
            title="DHE Pairing",
            notification_id=client._pairing_notification_id,
        )


    async def test_set_controlunit_name_writes_assign_command_and_confirms(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._last_device_info = {}
        sent_packets: list[dict[str, object]] = []
        client._message_packet = lambda payload: payload

        async def _post_packet(_ctx: object, packet: dict[str, object]) -> None:
            sent_packets.append(packet)

        client._post_packet = AsyncMock(side_effect=_post_packet)

        async def _request_app_value(_ctx: object, command: str) -> None:
            self.assertEqual(command, "get:ste.common.version:controlunitName")
            client._last_device_info["controlunit_name"] = "Bathroom DHE"

        client._request_app_value = AsyncMock(side_effect=_request_app_value)

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry

        confirmed = await DHEClient.set_controlunit_name(client, "  Bathroom DHE  ")

        self.assertEqual(confirmed, "Bathroom DHE")
        self.assertEqual(
            sent_packets,
            [
                {
                    "command": "assign:ste.common.version:controlunitName",
                    "value": "Bathroom DHE",
                }
            ],
        )
        client._request_app_value.assert_awaited_once()


    async def test_bridge_temperature_maximum_writes_assign_command(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        sent_packets: list[dict[str, object]] = []
        client._message_packet = lambda payload: payload

        async def _post_packet(_ctx: object, packet: dict[str, object]) -> None:
            sent_packets.append(packet)

        client._post_packet = AsyncMock(side_effect=_post_packet)

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry
        client._request_app_value = AsyncMock()

        confirmed = await DHEClient.bridge_temperature_maximum(client)

        self.assertTrue(confirmed)
        self.assertEqual(
            sent_packets,
            [
                {
                    "command": "assign:ste.common.temperature:maxOverride",
                    "value": True,
                }
            ],
        )
        client._request_app_value.assert_not_awaited()


    async def test_set_price_rolls_back_when_second_write_fails(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError

        client = DHEClient.__new__(DHEClient)
        euros_id = 100
        cents_id = 101
        client._last_measurements = {
            euros_id: 0.0,
            cents_id: 29.0,
        }

        calls: list[tuple[int, float]] = []

        async def _write_odb_value(odb_id: int, value):
            calls.append((odb_id, float(value)))
            if (odb_id, float(value)) == (cents_id, 5.0):
                raise DHEError("write failed")
            return float(value)

        client.write_odb_value = AsyncMock(side_effect=_write_odb_value)

        with self.assertRaises(DHEError):
            await DHEClient._set_price(
                client,
                1.05,
                euros_id,
                cents_id,
                max_value=9.99,
            )

        self.assertEqual(
            calls,
            [
                (euros_id, 1.0),
                (cents_id, 5.0),
                (cents_id, 29.0),
                (euros_id, 0.0),
            ],
        )


    async def test_set_price_rolls_back_known_components_when_cache_is_partial(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError

        client = DHEClient.__new__(DHEClient)
        euros_id = 100
        cents_id = 101
        client._last_measurements = {euros_id: 2.0}
        calls: list[tuple[int, float]] = []

        async def _write_odb_value(odb_id: int, value):
            calls.append((odb_id, float(value)))
            if (odb_id, float(value)) == (cents_id, 45.0):
                raise DHEError("write failed")
            return float(value)

        client.write_odb_value = AsyncMock(side_effect=_write_odb_value)

        with self.assertRaisesRegex(DHEError, "write failed"):
            await DHEClient._set_price(
                client,
                3.45,
                euros_id,
                cents_id,
                max_value=9.99,
            )

        self.assertEqual(
            calls,
            [
                (euros_id, 3.0),
                (cents_id, 45.0),
                (euros_id, 2.0),
            ],
        )


    async def test_set_price_rolls_back_when_runtime_error_fails_write(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        euros_id = 100
        cents_id = 101
        client._last_measurements = {
            euros_id: 0.0,
            cents_id: 29.0,
        }
        calls: list[tuple[int, float]] = []

        async def _write_odb_value(odb_id: int, value):
            calls.append((odb_id, float(value)))
            if (odb_id, float(value)) == (cents_id, 5.0):
                raise RuntimeError("unexpected invalid state")
            return float(value)

        client.write_odb_value = AsyncMock(side_effect=_write_odb_value)

        with self.assertRaisesRegex(RuntimeError, "unexpected invalid state"):
            await DHEClient._set_price(
                client,
                1.05,
                euros_id,
                cents_id,
                max_value=9.99,
            )

        self.assertEqual(
            calls,
            [
                (euros_id, 1.0),
                (cents_id, 5.0),
                (cents_id, 29.0),
                (euros_id, 0.0),
            ],
        )


    async def test_set_price_reports_rollback_failure(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError

        client = DHEClient.__new__(DHEClient)
        euros_id = 100
        cents_id = 101
        client._last_measurements = {
            euros_id: 0.0,
            cents_id: 29.0,
        }

        async def _write_odb_value(odb_id: int, value):
            if (odb_id, float(value)) == (cents_id, 5.0):
                raise DHEError("write failed")
            if (odb_id, float(value)) == (euros_id, 0.0):
                raise DHEError("rollback failed")
            return float(value)

        client.write_odb_value = AsyncMock(side_effect=_write_odb_value)

        with self.assertRaisesRegex(
            DHEError,
            "write failed; price rollback failed: ODB id 100: rollback failed",
        ):
            await DHEClient._set_price(
                client,
                1.05,
                euros_id,
                cents_id,
                max_value=9.99,
            )


    async def test_set_price_reports_runtime_rollback_failure(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError

        client = DHEClient.__new__(DHEClient)
        euros_id = 100
        cents_id = 101
        client._last_measurements = {
            euros_id: 0.0,
            cents_id: 29.0,
        }

        async def _write_odb_value(odb_id: int, value):
            if (odb_id, float(value)) == (cents_id, 5.0):
                raise RuntimeError("unexpected invalid state")
            if (odb_id, float(value)) == (euros_id, 0.0):
                raise RuntimeError("rollback invalid state")
            return float(value)

        client.write_odb_value = AsyncMock(side_effect=_write_odb_value)

        with self.assertRaisesRegex(
            DHEError,
            (
                "unexpected invalid state; price rollback failed: "
                "ODB id 100: rollback invalid state"
            ),
        ):
            await DHEClient._set_price(
                client,
                1.05,
                euros_id,
                cents_id,
                max_value=9.99,
            )


    async def test_save_token_creates_restrictive_file(self) -> None:
        client_module = _load_client()
        token_storage = _load_component_module("token_storage")
        DHEClient = client_module.DHEClient

        class _FakeHass:
            async def async_add_executor_job(self, func, *args):
                return func(*args)

        client = DHEClient.__new__(DHEClient)
        client.hass = _FakeHass()
        client._token = None

        with tempfile.TemporaryDirectory() as temp_dir:
            client.token_path = os.path.join(temp_dir, "token.txt")
            client._token_store = token_storage.LegacyFileTokenStore(
                client.hass,
                client.token_path,
            )
            await DHEClient._save_token(client, "super-secret-token")

            token_contents = await asyncio.to_thread(
                Path(client.token_path).read_text,
                encoding="utf-8",
            )
            self.assertEqual(token_contents, "super-secret-token")

            if os.name == "posix":
                mode = stat.S_IMODE(os.stat(client.token_path).st_mode)
                self.assertEqual(mode, stat.S_IRUSR | stat.S_IWUSR)


    async def test_set_temperature_memory_requires_confirmed_value(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError

        client = DHEClient.__new__(DHEClient)
        client._temperature_memory_generation = 1
        client._last_measurement_attributes = {}
        client._temperature_memory_ids = lambda _slot: (0, 700)
        client._refresh_temperature_memories = AsyncMock()
        client._temperature_memory_payload = lambda *_args, **_kwargs: {
            "name": "Dusche",
            "temperature": 38.0,
            "operation": "add_change",
        }
        client._post_packet = AsyncMock()
        client._message_packet = lambda payload: payload
        client._cached_temperature_memory_temperature = lambda _measurement_id: None

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry

        with self.assertRaisesRegex(DHEError, "was not confirmed"):
            await DHEClient.set_temperature_memory(client, 0, 38.0)


    async def test_set_temperature_memory_existing_slot_without_confirmation_is_rejected(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError

        client = DHEClient.__new__(DHEClient)
        client._temperature_memory_generation = 2
        client._last_measurement_attributes = {}
        client._temperature_memory_ids = lambda _slot: (0, 700)
        client._refresh_temperature_memories = AsyncMock()
        client._temperature_memory_payload = lambda *_args, **_kwargs: {
            "name": "Dusche",
            "temperature": 38.0,
            "id": 0,
            "operation": "add_change",
        }
        client._post_packet = AsyncMock()
        client._message_packet = lambda payload: payload
        client._cached_temperature_memory_temperature = lambda _measurement_id: 38.0
        client._handle_temperature_memory_item = unittest.mock.MagicMock()

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry

        with self.assertRaisesRegex(
            DHEError,
            "was not confirmed",
        ):
            await DHEClient.set_temperature_memory(client, 0, 38.0)

        self.assertEqual(client._temperature_memory_generation, 2)
        self.assertEqual(client._refresh_temperature_memories.await_count, 2)
        client._handle_temperature_memory_item.assert_not_called()


    async def test_set_temperature_memory_requires_generation_change_after_write(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError

        client = DHEClient.__new__(DHEClient)
        client._temperature_memory_generation = 0
        client._last_measurement_attributes = {}
        client._temperature_memory_ids = lambda _slot: (0, 700)

        refresh_calls = 0

        async def _refresh_memory(_ctx: object | None = None) -> None:
            nonlocal refresh_calls
            refresh_calls += 1
            if refresh_calls == 1:
                # Initial pre-write refresh changes generation and caches the slot.
                client._temperature_memory_generation = 1
                client._last_measurement_attributes[700] = {"name": "Dusche"}
            # Second refresh simulates no post-write update from the DHE.

        client._refresh_temperature_memories = AsyncMock(side_effect=_refresh_memory)
        client._temperature_memory_payload = lambda *_args, **_kwargs: {
            "name": "Dusche",
            "temperature": 38.0,
            "id": 0,
            "operation": "add_change",
        }
        client._post_packet = AsyncMock()
        client._message_packet = lambda payload: payload
        client._cached_temperature_memory_temperature = lambda _measurement_id: 38.0

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry

        with self.assertRaisesRegex(DHEError, "was not confirmed"):
            await DHEClient.set_temperature_memory(client, 0, 38.0)

        self.assertEqual(refresh_calls, 2)


    async def test_set_temperature_memory_name_without_confirmation_is_rejected(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError

        client = DHEClient.__new__(DHEClient)
        client._temperature_memory_generation = 2
        client._last_measurement_attributes = {}
        client._temperature_memory_ids = lambda _slot: (0, 700)
        client._refresh_temperature_memories = AsyncMock()
        client._temperature_memory_payload = lambda *_args, **_kwargs: {
            "name": "Family",
            "temperature": 38.0,
            "id": 0,
            "operation": "add_change",
        }
        client._post_packet = AsyncMock()
        client._message_packet = lambda payload: payload
        client._cached_temperature_memory_temperature = lambda _measurement_id: 38.0

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry

        with self.assertRaisesRegex(
            DHEError,
            "name was not confirmed",
        ):
            await DHEClient.set_temperature_memory_name(
                client,
                0,
                "Family",
            )

        self.assertEqual(client._temperature_memory_generation, 2)
        self.assertEqual(client._refresh_temperature_memories.await_count, 2)


    async def test_set_temperature_memory_name_readback_mismatch_is_rejected(
        self,
    ) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient
        DHEError = client_module.DHEError

        client = DHEClient.__new__(DHEClient)
        client._temperature_memory_generation = 0
        client._last_measurement_attributes = {}
        client._temperature_memory_ids = lambda _slot: (0, 700)

        async def _refresh_memory(_ctx: object | None = None) -> None:
            client._temperature_memory_generation += 1
            client._last_measurement_attributes[700] = {"name": "WrongName"}

        client._refresh_temperature_memories = AsyncMock(side_effect=_refresh_memory)
        client._temperature_memory_payload = lambda *_args, **_kwargs: {
            "name": "Family",
            "temperature": 38.0,
            "id": 0,
            "operation": "add_change",
        }
        client._post_packet = AsyncMock()
        client._message_packet = lambda payload: payload
        client._cached_temperature_memory_temperature = lambda _measurement_id: 38.0

        async def _run_with_retry(_message, operation):
            return await operation(object())

        client._run_command_with_reconnect_retry = _run_with_retry

        with self.assertRaisesRegex(
            DHEError,
            "name readback was 'WrongName', expected 'Family'",
        ):
            await DHEClient.set_temperature_memory_name(
                client,
                0,
                "Family",
            )


    async def test_timer_reset_restores_remaining_to_configured_duration(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._last_measurements = {
            protocol_module.ID_SHOWER_TIMER_DURATION: 5.0,
            protocol_module.ID_SHOWER_TIMER_REMAINING: 0.0,
            protocol_module.ID_SHOWER_TIMER_ACTIVATION: True,
        }
        client._measurement_callbacks = set()
        client._pending_write_future = None
        client._pending_write_id = None
        client._pending_write_expected = None
        captured_calls: list[tuple[int, object]] = []
        client._measurement_callbacks.add(
            lambda measurement_id, value: captured_calls.append((measurement_id, value))
        )

        DHEClient._handle_app_timer_reset(
            client,
            "set:ste.app.showerTimer:reset",
        )

        self.assertEqual(
            client._last_measurements[protocol_module.ID_SHOWER_TIMER_REMAINING],
            5.0,
        )
        self.assertFalse(
            client._last_measurements[protocol_module.ID_SHOWER_TIMER_ACTIVATION]
        )
        self.assertEqual(
            captured_calls,
            [
                (protocol_module.ID_SHOWER_TIMER_REMAINING, 5.0),
                (protocol_module.ID_SHOWER_TIMER_ACTIVATION, False),
            ],
        )


    async def test_child_safety_off_does_not_request_temperature_max_override_readback(
        self,
    ) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._last_measurements = {protocol_module.ID_CHILD_SAFETY_ACTIVE: True}
        client._request_app_value = AsyncMock()

        def _handle_measurement(
            odb_id: int,
            value: object,
            *,
            force_update: bool = False,
        ) -> None:
            del force_update
            client._last_measurements[odb_id] = value

        client._handle_measurement = _handle_measurement
        client._update_diagnostics = Mock()

        DHEClient._handle_odb_child_safety_active_value(client, False)

        client._request_app_value.assert_not_awaited()
        client._update_diagnostics.assert_called_once_with(
            child_safety_active=False
        )


    async def test_child_safety_off_updates_diagnostics_when_already_off(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._last_measurements = {protocol_module.ID_CHILD_SAFETY_ACTIVE: False}
        client._request_app_value = AsyncMock()

        def _handle_measurement(
            odb_id: int,
            value: object,
            *,
            force_update: bool = False,
        ) -> None:
            del force_update
            client._last_measurements[odb_id] = value

        client._handle_measurement = _handle_measurement
        client._update_diagnostics = Mock()

        DHEClient._handle_odb_child_safety_active_value(client, False)

        client._request_app_value.assert_not_awaited()
        client._update_diagnostics.assert_called_once_with(
            child_safety_active=False
        )


    async def test_shower_timer_writes_use_shower_timer_path(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._last_measurements = {protocol_module.ID_SHOWER_TIMER_DURATION: 5.0}
        client._write_app_value = AsyncMock(side_effect=[5.0, False, 5.0])
        client._handle_measurement = Mock()

        duration = await DHEClient.set_shower_timer_duration_minutes(client, 5.0)
        activation = await DHEClient.set_shower_timer_activation(client, False)
        reset = await DHEClient.reset_shower_timer(client)

        self.assertEqual(duration, 5.0)
        self.assertFalse(activation)
        self.assertTrue(reset)
        self.assertEqual(
            client._write_app_value.await_args_list[0].args,
            (
                "assign:ste.app.showerTimer:durationMilliseconds",
                300000,
                protocol_module.ID_SHOWER_TIMER_DURATION,
                5.0,
            ),
        )
        self.assertEqual(
            client._write_app_value.await_args_list[1].args,
            (
                "assign:ste.app.showerTimer:activation",
                False,
                protocol_module.ID_SHOWER_TIMER_ACTIVATION,
                False,
            ),
        )
        self.assertEqual(
            client._write_app_value.await_args_list[2].args,
            (
                "assign:ste.app.showerTimer:reset",
                True,
                protocol_module.ID_SHOWER_TIMER_REMAINING,
                5.0,
            ),
        )
        client._handle_measurement.assert_any_call(
            protocol_module.ID_SHOWER_TIMER_REMAINING,
            5.0,
            force_update=True,
        )
        client._handle_measurement.assert_any_call(
            protocol_module.ID_SHOWER_TIMER_ACTIVATION,
            False,
            force_update=True,
        )


    async def test_brush_timer_writes_keep_brush_timer_path(self) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._last_measurements = {protocol_module.ID_BRUSH_TIMER_DURATION: 4.0}
        client._write_app_value = AsyncMock(side_effect=[4.0, True, 4.0])
        client._handle_measurement = Mock()

        duration = await DHEClient.set_brush_timer_duration_minutes(client, 4.0)
        activation = await DHEClient.set_brush_timer_activation(client, True)
        reset = await DHEClient.reset_brush_timer(client)

        self.assertEqual(duration, 4.0)
        self.assertTrue(activation)
        self.assertTrue(reset)
        self.assertEqual(
            client._write_app_value.await_args_list[0].args,
            (
                "assign:ste.app.brushTimer:durationMilliseconds",
                240000,
                protocol_module.ID_BRUSH_TIMER_DURATION,
                4.0,
            ),
        )
        self.assertEqual(
            client._write_app_value.await_args_list[1].args,
            (
                "assign:ste.app.brushTimer:activation",
                True,
                protocol_module.ID_BRUSH_TIMER_ACTIVATION,
                True,
            ),
        )
        self.assertEqual(
            client._write_app_value.await_args_list[2].args,
            (
                "assign:ste.app.brushTimer:reset",
                True,
                protocol_module.ID_BRUSH_TIMER_REMAINING,
                4.0,
            ),
        )
        client._handle_measurement.assert_any_call(
            protocol_module.ID_BRUSH_TIMER_REMAINING,
            4.0,
            force_update=True,
        )
        client._handle_measurement.assert_any_call(
            protocol_module.ID_BRUSH_TIMER_ACTIVATION,
            False,
            force_update=True,
        )


    async def test_app_read_source_matches_get_request_to_set_readback(self) -> None:
        client_module = _load_client()
        DHEClient = client_module.DHEClient

        client = DHEClient.__new__(DHEClient)
        client._pending_app_read_deadlines = {}

        DHEClient._mark_app_read_requested(client, "get:ste.app.radio:station")

        self.assertTrue(
            DHEClient._app_read_source(client, "set:ste.app.radio:station")
        )
        self.assertFalse(
            DHEClient._app_read_source(client, "set:ste.app.radio:station")
        )


    async def test_pending_diagnostic_zero_set_updates_remain_runtime_updates(
        self,
    ) -> None:
        client_module = _load_client()
        protocol_module = _load_protocol()
        client_types = _load_component_module("client_types")
        DHEClient = client_module.DHEClient
        DHEEvent = client_types.DHEEvent

        client = DHEClient.__new__(DHEClient)
        client._diagnostic_callbacks = set()
        client._diagnostic_state = {}
        client._handle_measurement = Mock()
        client._last_message_monotonic = None
        client._message_count = 0
        client._pending_odb_read_deadlines = {}
        client._odb_value_handlers = {}

        odb_id = protocol_module.ID_ODB_HOT_WATER_VOLUME
        DHEClient._mark_odb_read_requested(client, odb_id)
        await DHEClient._handle_runtime_event(
            client,
            DHEEvent(
                "message",
                {
                    "command": protocol_module.ODB_SET_COMMAND,
                    "value": {"id": odb_id, "value": 0, "isValid": True},
                },
            ),
        )

        client._handle_measurement.assert_called_once_with(
            odb_id,
            0.0,
            force_update=False,
        )
        self.assertTrue(DHEClient._consume_odb_read_request(client, odb_id))
        self.assertEqual(client._runtime_parser_stats["odb_value"], 1)
