"""Transport URL, packet and token helpers for the DHE client."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import stat
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import aiohttp

from .client_diagnostics import summarize_diagnostic_value as _summarize_diagnostic_value
from .client_types import DHEEvent, DHESession
from .engineio_helpers import balanced_json_array as _balanced_json_array
from .protocol import NS

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class DHEClientTransportHelpersMixin:
    """Build transport frames and persist DHE pairing tokens."""

    if TYPE_CHECKING:
        base_url: str
        hass: HomeAssistant
        port: int
        token_path: str
        _socketio_message_id: int
        _token: str | None
        _url_host: str

    def _poll_url(
        self,
        token: str,
        sid: str | None,
        websocket_sid: str | None = None,
    ) -> str:
        token_q = quote(token or "", safe="")
        t = format(int(time.time() * 1000), "x")
        websocket_part = ""
        if websocket_sid:
            websocket_part = f"&websocketSid={quote(websocket_sid, safe='')}"
        if sid:
            sid_q = quote(sid, safe="")
            return (
                f"{self.base_url}/socket.io/?EIO=3&transport=polling"
                f"&sid={sid_q}{websocket_part}&token={token_q}&t={t}"
            )
        return (
            f"{self.base_url}/socket.io/?EIO=3&transport=polling"
            f"{websocket_part}&token={token_q}&t={t}"
        )

    def _websocket_url_candidates(
        self,
        ctx: DHESession,
    ) -> tuple[tuple[str, str, str], ...]:
        websocket_sid = ctx.websocket_sid or ctx.sid
        candidates = [
            (
                "websocket-sid",
                websocket_sid,
                self._websocket_url(ctx.url_token, websocket_sid),
            ),
        ]
        if ctx.websocket_sid:
            candidates.extend(
                [
                    (
                        "polling-sid",
                        ctx.sid,
                        self._websocket_url(ctx.url_token, ctx.sid),
                    ),
                ]
            )
        return tuple(candidates)

    def _websocket_url(self, token: str, sid: str) -> str:
        token_q = quote(token or "", safe="")
        sid_q = quote(sid, safe="")
        return (
            f"ws://{self._url_host}:{self.port}/socket.io/"
            f"?token={token_q}&EIO=3&transport=websocket&sid={sid_q}"
        )

    def _websocket_headers(self, sid: str) -> dict[str, str]:
        return {
            "Cache-Control": "no-cache",
            "Cookie": f"io={sid}",
            "Origin": self.base_url,
            "Pragma": "no-cache",
        }

    @staticmethod
    def _websocket_message_packet(message: Any) -> str:
        if message.type == aiohttp.WSMsgType.TEXT:
            return str(message.data)
        if message.type == aiohttp.WSMsgType.BINARY:
            return bytes(message.data).decode("utf-8", errors="replace")
        return ""

    def _event_packet(self, event: str, data: Any) -> str:
        return f"42/{NS},{json.dumps([event, data], separators=(',', ':'))}"

    def _message_packet(self, payload: dict[str, Any]) -> str:
        message_id = self._next_socketio_message_id()
        return (
            f"42/{NS},{message_id}"
            f"{json.dumps(['message', payload], separators=(',', ':'))}"
        )

    def _next_socketio_message_id(self) -> int:
        message_id = self._socketio_message_id
        self._socketio_message_id = 1 if message_id >= 999 else message_id + 1
        return message_id

    def _parse_socketio_events(self, packets: list[str]) -> list[DHEEvent]:
        out: list[DHEEvent] = []
        for raw_packet in packets:
            packet = raw_packet.strip("\x00\x1e\ufffd")
            if not packet:
                continue
            pos = 0
            while pos < len(packet):
                match = re.search(r"42(?:/1\.0\.0,)?\d*", packet[pos:])
                if not match:
                    break
                frame_start = pos + match.start()
                json_text, next_pos = _balanced_json_array(packet, frame_start)
                if not json_text:
                    break
                try:
                    parsed = json.loads(json_text)
                    if isinstance(parsed, list) and parsed:
                        name = str(parsed[0])
                        data = parsed[1] if len(parsed) > 1 else None
                        out.append(DHEEvent(name, data))
                except json.JSONDecodeError:
                    _LOGGER.debug(
                        "Could not parse Socket.IO JSON frame: %r",
                        _summarize_diagnostic_value(json_text),
                    )
                pos = next_pos
        return out

    async def _load_token(self) -> str:
        if self._token:
            return self._token

        def _read() -> str:
            if not os.path.exists(self.token_path):
                return ""
            with open(self.token_path, encoding="utf-8") as file:
                return file.read().strip()

        token = await self.hass.async_add_executor_job(_read)
        if token and (len(token) < 20 or any(ch.isspace() for ch in token)):
            _LOGGER.warning("Ignoring malformed stored DHE token at %s", self.token_path)
            token = ""
        self._token = token
        return self._token or ""

    async def _save_token(self, token: str) -> None:
        self._token = token

        def _write() -> None:
            token_dir = os.path.dirname(self.token_path)
            os.makedirs(token_dir, exist_ok=True)
            tmp_path = f"{self.token_path}.tmp"
            file_descriptor = os.open(
                tmp_path,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                stat.S_IRUSR | stat.S_IWUSR,
            )
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as file:
                file.write(token)
            with contextlib.suppress(OSError):
                os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(tmp_path, self.token_path)

        await self.hass.async_add_executor_job(_write)

    async def _clear_token(self) -> None:
        self._token = ""

        def _delete() -> None:
            with contextlib.suppress(FileNotFoundError):
                os.remove(self.token_path)

        await self.hass.async_add_executor_job(_delete)
