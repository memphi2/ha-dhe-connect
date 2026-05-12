"""Pure pairing mapping helpers."""

from __future__ import annotations

from typing import Any


CONNECTIVITY_ERROR_PARTS = (
    "connection refused",
    "cannot connect",
    "get ",
    "post ",
    "socket",
    "session",
    "websocket",
)


def pairing_result_success(result: Any) -> bool | None:
    """Map a DHE pairing result payload to success, failure, or unknown."""
    if isinstance(result, bool):
        return result
    if isinstance(result, dict):
        for key in ("success", "paired", "accepted", "result"):
            if key in result:
                return pairing_result_success(result[key])
        return None
    if isinstance(result, str):
        normalized = result.strip().casefold()
        if normalized in {"true", "ok", "success", "successful", "accepted", "paired"}:
            return True
        if normalized in {
            "false",
            "failed",
            "failure",
            "rejected",
            "denied",
            "cancelled",
            "canceled",
        }:
            return False
    return None


def map_pairing_error(error: BaseException, pairing_state: str) -> str:
    """Map setup pairing/auth failures to config-flow error keys."""
    message = str(error).casefold()
    state = pairing_state.casefold()

    if state == "failed":
        if "reject" in message:
            return "pairing_rejected"
        if _is_connectivity_error(message):
            return "cannot_connect"
        if "timeout" in message:
            return "pairing_timeout"
        return "pairing_failed"

    if _is_connectivity_error(message):
        return "cannot_connect"

    if "pairing confirmation rejected" in message or "rejected on dhe" in message:
        return "pairing_rejected"

    if "auth timeout: no authenticated event received" in message:
        return "auth_timeout"

    if "token request timeout" in message:
        return "pairing_token_timeout"

    if (
        "authenticated, but dhe pairing confirmation was not completed in time"
        in message
    ) or (
        "token received but dhe pairing confirmation did not complete in time"
        in message
    ):
        return "pairing_confirm_after_auth_timeout"

    if state == "waiting_for_confirmation":
        return "pairing_not_confirmed"

    if state in {"requesting_token", "token_received", "confirmed", "result_received"}:
        return "pairing_token_timeout"

    if state == "authenticated_pending_confirmation":
        return "pairing_confirm_after_auth_timeout"

    if isinstance(error, TimeoutError) or "timeout" in message:
        return "pairing_timeout"

    if "authenticated" in message or "authenticate" in message:
        return "auth_failed"

    return "pairing_failed"


def pairing_notification_text(state: str, language: str) -> tuple[str, str]:
    """Return localized pairing notification title and message."""
    if language.lower().startswith("de"):
        title = "DHE-Pairing"
        messages = {
            "setup_requested": (
                "Home Assistant startet das Pairing. Bitte die Kopplungsanfrage am DHE bestätigen."
            ),
            "repair_requested": (
                "Das lokale Pairing-Token wurde verworfen. "
                "Bitte eine Kopplungsanfrage am DHE bestätigen, falls sie erscheint."
            ),
            "requesting_token": (
                "Home Assistant fordert ein neues Pairing-Token an. "
                "Bitte eine Kopplung am DHE bestätigen, falls angefordert."
            ),
            "waiting_for_confirmation": (
                "Der DHE wartet auf die Pairing-Bestätigung. "
                "Bitte die Bestätigung am Gerät vollständig abschließen."
            ),
            "confirmed": "Pairing bestätigt. Home Assistant wartet auf das neue Token.",
            "result_received": "Pairing-Rückmeldung erhalten. Home Assistant wartet auf das neue Token.",
            "token_received": "Neues Pairing-Token erhalten. Pairing-Status wird geprüft.",
            "fallback_no_device_confirmation": (
                "Der DHE hat keine Geräte-Bestätigung angefordert. Anmeldung läuft mit Token."
            ),
            "authenticated_pending_confirmation": (
                "Anmeldung erhalten, warte auf Pairing-Bestätigung am DHE."
            ),
            "authenticated_without_device_confirmation": (
                "Anmeldung abgeschlossen. Der DHE hat keine Geräte-Bestätigung angefordert."
            ),
            "authenticated": "Pairing abgeschlossen. Home Assistant ist mit dem DHE verbunden.",
            "failed": (
                "Pairing fehlgeschlagen. Bitte am DHE prüfen und danach "
                "'Pairing erneuern' erneut drücken."
            ),
        }
        return title, messages.get(state, "Pairing-Status wurde aktualisiert.")

    title = "DHE pairing"
    messages = {
        "setup_requested": (
            "Home Assistant is starting pairing. Confirm the pairing request on the DHE."
        ),
        "repair_requested": (
            "The local pairing token was discarded. Confirm the pairing request "
            "on the DHE display if it appears."
        ),
        "requesting_token": (
            "Home Assistant is requesting a new pairing token. Confirm pairing "
            "on the DHE display if requested."
        ),
        "waiting_for_confirmation": (
            "The DHE is waiting for pairing confirmation. Confirm the request "
            "on the device and complete the confirmation there."
        ),
        "confirmed": "Pairing confirmed. Home Assistant is waiting for the new token.",
        "result_received": "Pairing result received. Home Assistant is waiting for the new token.",
        "token_received": "New pairing token received. Verifying pairing status.",
        "fallback_no_device_confirmation": (
            "The DHE did not request on-device confirmation. Continuing authentication with token."
        ),
        "authenticated_pending_confirmation": (
            "Authentication received, waiting for pairing confirmation on the DHE."
        ),
        "authenticated_without_device_confirmation": (
            "Authentication completed. The DHE did not request on-device confirmation."
        ),
        "authenticated": "Pairing complete. Home Assistant is connected to the DHE.",
        "failed": (
            "Pairing failed. Check the DHE display and press "
            "'Repair pairing' again."
        ),
    }
    return title, messages.get(state, "Pairing status was updated.")


def _is_connectivity_error(message: str) -> bool:
    return any(part in message for part in CONNECTIVITY_ERROR_PARTS)
