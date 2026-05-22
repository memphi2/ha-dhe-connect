"""Pairing progress and notification helpers for the DHE client."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import TYPE_CHECKING, Any

from homeassistant.components import persistent_notification

from .client_diagnostics import (
    diagnostic_error as _diagnostic_error,
    diagnostic_timestamp as _diagnostic_timestamp,
    summarize_diagnostic_value as _summarize_diagnostic_value,
)
from .pairing_helpers import (
    pairing_notification_text,
    pairing_result_success as _pairing_result_success,
)

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

MAX_PAIRING_AUTO_RETRIES = 3
PAIRING_NOTIFICATION_ID_PREFIX = "stiebel_dhe_connect_pairing"
PAIRING_CONFIRM_HINT_NOTIFICATION_ID_PREFIX = "stiebel_dhe_connect_pairing_confirm"
_PAIRING_NOTIFICATION_HOST_SAFE_RE = re.compile(r"[^A-Za-z0-9_-]+")


class DHEClientPairingMixin:
    """Pairing state, diagnostics and persistent-notification helpers."""

    if TYPE_CHECKING:
        hass: HomeAssistant
        host: str
        port: int
        _diagnostic_state: dict[str, Any]
        _manual_pairing_requested: bool
        _pairing_active: bool
        _pairing_confirmed_success: bool
        _pairing_failed_explicit: bool
        _pairing_request_seen: bool
        _pairing_retry_attempts: int
        _pause_auto_reconnect_for_pairing: bool
        _require_pairing_confirmation: bool

        def _update_diagnostics(self, **updates: Any) -> None: ...

    def _begin_manual_pairing(self, state: str, message: str, *, notify: bool) -> None:
        """Prepare a pairing attempt that must end with an explicit DHE result."""
        self._pairing_active = True
        self._require_pairing_confirmation = True
        self._pairing_request_seen = False
        self._pairing_confirmed_success = False
        self._pairing_failed_explicit = False
        self._manual_pairing_requested = True
        self._pause_auto_reconnect_for_pairing = False
        self._pairing_retry_attempts = 0
        self._record_pairing_progress(
            state,
            message,
            notify=notify,
        )

    def _record_pairing_progress(
        self,
        state: str,
        message: str,
        *,
        notify: bool = False,
        result: Any | None = None,
    ) -> None:
        previous_state = self._diagnostic_state.get("pairing_state")
        previous_message = self._diagnostic_state.get("pairing_message")
        previous_result = self._diagnostic_state.get("pairing_result")
        next_result = (
            _summarize_diagnostic_value(result)
            if result is not None
            else previous_result
        )
        notify_now = notify and (
            state != previous_state
            or message != previous_message
            or next_result != previous_result
        )
        updates: dict[str, Any] = {
            "pairing_state": state,
            "pairing_message": message,
            "pairing_updated_at": _diagnostic_timestamp(),
        }
        if result is not None:
            updates["pairing_result"] = next_result
        self._update_diagnostics(**updates)
        if notify_now:
            self._notify_pairing_progress(state)

    def _record_pairing_requested(self) -> None:
        self._pairing_request_seen = True
        self._pairing_confirmed_success = False
        self._pairing_failed_explicit = False
        if self._diagnostic_state.get("pairing_state") == "waiting_for_confirmation":
            return
        _LOGGER.info("DHE pairing requested. Confirm the request on the DHE display.")
        self._pairing_active = True
        self._record_pairing_progress(
            "waiting_for_confirmation",
            "DHE requested pairing confirmation.",
            notify=True,
        )

    def _record_pairing_result(self, result: Any) -> None:
        success = _pairing_result_success(result)
        if success is False:
            _LOGGER.warning(
                "DHE pairing was rejected or failed: %s",
                _summarize_diagnostic_value(result),
            )
            self._pairing_confirmed_success = False
            self._pairing_failed_explicit = True
            self._record_pairing_progress(
                "failed",
                "DHE pairing was rejected or failed.",
                notify=True,
                result=result,
            )
            self._pairing_active = False
            return

        state = "confirmed" if success is True else "result_received"
        if success is True:
            self._pairing_confirmed_success = True
            self._pairing_failed_explicit = False
        message = (
            "DHE pairing confirmed; waiting for token."
            if success is True
            else "DHE pairing result received; waiting for token."
        )
        _LOGGER.debug(
            "DHE pairing result received: %s",
            _summarize_diagnostic_value(result),
        )
        self._record_pairing_progress(
            state,
            message,
            notify=True,
            result=result,
        )

    def _record_pairing_failed(self, error: BaseException) -> None:
        self._manual_pairing_requested = False
        self._pairing_retry_attempts += 1
        attempts = self._pairing_retry_attempts
        auto_retry_allowed = attempts < MAX_PAIRING_AUTO_RETRIES
        retry_hint = (
            f"Pairing attempt {attempts}/{MAX_PAIRING_AUTO_RETRIES} failed; "
            "retrying automatically."
            if auto_retry_allowed
            else (
                f"Pairing attempt {attempts}/{MAX_PAIRING_AUTO_RETRIES} failed; "
                "waiting for manual retry."
            )
        )
        self._record_pairing_progress(
            "failed",
            f"{_diagnostic_error(error)} ({retry_hint})",
            notify=True,
        )
        # Allow bounded automatic retries before switching to manual-only mode.
        self._pause_auto_reconnect_for_pairing = not auto_retry_allowed
        self._pairing_active = False

    def _notify_pairing_progress(self, state: str) -> None:
        # Cleanup legacy pairing notifications without a port suffix.
        try:
            persistent_notification.async_dismiss(
                self.hass,
                self._legacy_pairing_confirmation_notification_id,
            )
            persistent_notification.async_dismiss(
                self.hass,
                self._legacy_pairing_confirmation_notification_id_with_port,
            )
            persistent_notification.async_dismiss(
                self.hass,
                self._legacy_pairing_notification_id,
            )
            persistent_notification.async_dismiss(
                self.hass,
                self._legacy_pairing_notification_id_with_port,
            )
            persistent_notification.async_dismiss(
                self.hass,
                self._pairing_confirmation_notification_id,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug(
                "Could not dismiss legacy pairing notifications: %s",
                _diagnostic_error(err),
            )
        title, message = self._pairing_notification_text(state)
        persistent_notification.async_create(
            self.hass,
            message,
            title=title,
            notification_id=self._pairing_notification_id,
        )

    @staticmethod
    def _safe_host_for_notification(host: str) -> str:
        return _PAIRING_NOTIFICATION_HOST_SAFE_RE.sub("_", host)

    @property
    def _pairing_notification_target_id(self) -> str:
        normalized_host = str(self.host).strip().lower().rstrip(".")
        target = f"{normalized_host}:{int(self.port)}"
        return hashlib.sha256(target.encode("utf-8")).hexdigest()[:12]

    @property
    def _pairing_notification_id(self) -> str:
        return f"{PAIRING_NOTIFICATION_ID_PREFIX}_{self._pairing_notification_target_id}"

    @property
    def _legacy_pairing_notification_id(self) -> str:
        safe_host = self._safe_host_for_notification(self.host)
        return f"{PAIRING_NOTIFICATION_ID_PREFIX}_{safe_host}"

    @property
    def _legacy_pairing_notification_id_with_port(self) -> str:
        safe_host = self._safe_host_for_notification(self.host)
        return f"{PAIRING_NOTIFICATION_ID_PREFIX}_{safe_host}_{self.port}"

    @property
    def _pairing_confirmation_notification_id(self) -> str:
        return (
            f"{PAIRING_CONFIRM_HINT_NOTIFICATION_ID_PREFIX}_"
            f"{self._pairing_notification_target_id}"
        )

    @property
    def _legacy_pairing_confirmation_notification_id(self) -> str:
        safe_host = self._safe_host_for_notification(self.host)
        return f"{PAIRING_CONFIRM_HINT_NOTIFICATION_ID_PREFIX}_{safe_host}"

    @property
    def _legacy_pairing_confirmation_notification_id_with_port(self) -> str:
        safe_host = self._safe_host_for_notification(self.host)
        return f"{PAIRING_CONFIRM_HINT_NOTIFICATION_ID_PREFIX}_{safe_host}_{self.port}"

    def _pairing_notification_text(self, state: str) -> tuple[str, str]:
        language = str(getattr(self.hass.config, "language", "") or "").lower()
        return pairing_notification_text(state, language)
