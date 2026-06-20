"""DHE web-interface version discovery."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

import aiohttp

from .client_diagnostics import diagnostic_error as _diagnostic_error
from .client_types import MeasurementValue
from .protocol import ID_PROTOCOL_VERSION

_LOGGER = logging.getLogger(__name__)

WEB_INTERFACE_VERSION_SOURCE = "web:index"
WEB_INTERFACE_VERSION_TIMEOUT_SECONDS = 4.0
WEB_INTERFACE_VERSION_MAX_LENGTH = 32

_WEB_APP_VERSION_PATTERNS = (
    re.compile(r"""manifest=["']/manifest-(?P<version>[^"']+)\.appcache["']"""),
    re.compile(r"""assets/ste-dhe-(?P<version>[^"'/]+)\.(?:js|css)"""),
)
_WEB_APP_VERSION_VALUE = re.compile(r"[0-9][0-9A-Za-z._-]{0,31}")


def extract_web_app_version(html: str) -> str | None:
    """Extract the DHE web app version from the web interface root HTML."""
    for pattern in _WEB_APP_VERSION_PATTERNS:
        match = pattern.search(html)
        if match is None:
            continue
        version = _normalize_web_app_version(match.group("version"))
        if version is not None:
            return version
    return None


def _normalize_web_app_version(value: str) -> str | None:
    version = value.strip()
    if (
        not version
        or len(version) > WEB_INTERFACE_VERSION_MAX_LENGTH
        or _WEB_APP_VERSION_VALUE.fullmatch(version) is None
    ):
        return None
    return version


class DHEClientWebVersionMixin:
    """Fetch and publish the DHE browser UI version."""

    if TYPE_CHECKING:
        base_url: str
        _last_device_info: dict[str, Any]
        _last_measurements: dict[int, MeasurementValue]
        _session: aiohttp.ClientSession

        def _handle_measurement(
            self,
            odb_id: int,
            value: MeasurementValue,
            *,
            force_update: bool = False,
        ) -> None: ...

        def _publish_device_info_measurement(self) -> None: ...

    async def _request_web_interface_version(self) -> None:
        """Request the root page and publish the browser UI version if present."""
        try:
            timeout = aiohttp.ClientTimeout(
                total=WEB_INTERFACE_VERSION_TIMEOUT_SECONDS,
            )
            async with self._session.get(self.base_url, timeout=timeout) as response:
                if response.status >= 400:
                    return
                html = await response.text()
        except (
            UnicodeDecodeError,
            aiohttp.ClientError,
            OSError,
            RuntimeError,
            TimeoutError,
        ) as err:
            _LOGGER.debug(
                "Could not read DHE web interface version: %s",
                _diagnostic_error(err),
            )
            return

        version = extract_web_app_version(html)
        if version is None:
            return
        self._handle_web_interface_version(version)

    def _handle_web_interface_version(self, version: str) -> None:
        """Publish the display protocol version from the DHE web UI version."""
        previous = self._last_measurements.get(ID_PROTOCOL_VERSION)
        self._last_device_info["web_app_version"] = version
        self._last_device_info["protocol_version"] = version
        self._last_device_info["protocol_version_source"] = WEB_INTERFACE_VERSION_SOURCE
        self._publish_device_info_measurement()
        self._handle_measurement(
            ID_PROTOCOL_VERSION,
            version,
            force_update=previous != version,
        )
