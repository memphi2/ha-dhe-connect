"""Device information write helpers for the DHE client."""

from __future__ import annotations

from .client_command_context import command_context as _command_context
from .client_constants import APP_COMMAND_CONFIRMATION_TIMEOUT
from .client_types import DHEError, DHESession
from .flow_helpers import wait_until as _wait_until
from .protocol import (
    CONTROLUNIT_NAME_ASSIGN_COMMAND,
    CONTROLUNIT_NAME_GET_COMMAND,
    CONTROLUNIT_NAME_MAX_LENGTH,
)


class DHEClientDeviceInfoCommandsMixin:
    """Writable DHE device-information commands."""

    async def set_controlunit_name(self, name: str) -> str:
        """Set the DHE device/control-unit name."""
        requested_name = str(name).strip()
        if not requested_name:
            raise DHEError("DHE device name must not be empty")
        if len(requested_name) > CONTROLUNIT_NAME_MAX_LENGTH:
            raise DHEError(
                "DHE device name must not exceed "
                f"{CONTROLUNIT_NAME_MAX_LENGTH} characters"
            )

        client = _command_context(self)

        async def _operation(ctx: DHESession) -> str:
            await client._post_packet(
                ctx,
                client._message_packet({
                    "command": CONTROLUNIT_NAME_ASSIGN_COMMAND,
                    "value": requested_name,
                }),
            )
            await client._request_app_value(ctx, CONTROLUNIT_NAME_GET_COMMAND)
            if await _wait_for_controlunit_name(client, requested_name):
                return requested_name

            confirmed_name = str(
                client._last_device_info.get("controlunit_name", "")
            ).strip()
            raise DHEError(
                f"DHE device name readback was {confirmed_name!r}, "
                f"expected {requested_name!r}"
            )

        return await client._run_command_with_reconnect_retry(
            "Could not set DHE device name",
            _operation,
        )


async def _wait_for_controlunit_name(client: object, requested_name: str) -> bool:
    context = _command_context(client)
    return await _wait_until(
        lambda: str(context._last_device_info.get("controlunit_name", "")).strip()
        == requested_name,
        timeout_seconds=APP_COMMAND_CONFIRMATION_TIMEOUT,
    )
