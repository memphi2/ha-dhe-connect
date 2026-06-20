"""Tests for pairing mapping helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PAIRING_HELPERS = (
    ROOT / "custom_components" / "stiebel_dhe_connect" / "pairing_helpers.py"
)


def _load_pairing_helpers():
    spec = importlib.util.spec_from_file_location("pairing_helpers", PAIRING_HELPERS)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestPairingResultSuccess(unittest.TestCase):
    """Validate pairing result payload mapping."""

    def setUp(self) -> None:
        self.helpers = _load_pairing_helpers()

    def test_pairing_result_success_accepts_bool_dict_and_string_values(self) -> None:
        self.assertTrue(self.helpers.pairing_result_success(True))
        self.assertTrue(self.helpers.pairing_result_success({"accepted": "ok"}))
        self.assertFalse(self.helpers.pairing_result_success("rejected"))
        self.assertFalse(self.helpers.pairing_result_success({"result": "failed"}))
        self.assertIsNone(self.helpers.pairing_result_success({"other": True}))
        self.assertIsNone(self.helpers.pairing_result_success("unknown"))


class TestPairingErrorMapping(unittest.TestCase):
    """Validate setup pairing error mapping."""

    def setUp(self) -> None:
        self.helpers = _load_pairing_helpers()

    def test_map_pairing_error_prioritizes_failed_rejected_state(self) -> None:
        self.assertEqual(
            self.helpers.map_pairing_error(Exception("Rejected on DHE"), "failed"),
            "pairing_rejected",
        )

    def test_map_pairing_error_maps_connectivity_failures(self) -> None:
        self.assertEqual(
            self.helpers.map_pairing_error(Exception("websocket closed"), ""),
            "cannot_connect",
        )

    def test_map_pairing_error_maps_waiting_for_confirmation(self) -> None:
        self.assertEqual(
            self.helpers.map_pairing_error(Exception("still waiting"), "waiting_for_confirmation"),
            "pairing_not_confirmed",
        )

    def test_map_pairing_error_maps_token_and_auth_timeouts(self) -> None:
        self.assertEqual(
            self.helpers.map_pairing_error(Exception("token request timeout"), ""),
            "pairing_token_timeout",
        )
        self.assertEqual(
            self.helpers.map_pairing_error(
                Exception("auth timeout: no authenticated event received"),
                "",
            ),
            "auth_timeout",
        )
        self.assertEqual(
            self.helpers.map_pairing_error(TimeoutError("timed out"), ""),
            "pairing_timeout",
        )

    def test_map_pairing_error_maps_confirm_after_auth_timeout(self) -> None:
        self.assertEqual(
            self.helpers.map_pairing_error(
                Exception(
                    "authenticated, but DHE pairing confirmation was not completed in time"
                ),
                "",
            ),
            "pairing_confirm_after_auth_timeout",
        )

    def test_map_pairing_error_handles_failed_state_sub_paths(self) -> None:
        self.assertEqual(
            self.helpers.map_pairing_error(Exception("socket closed"), "failed"),
            "cannot_connect",
        )
        self.assertEqual(
            self.helpers.map_pairing_error(Exception("timeout while pairing"), "failed"),
            "pairing_timeout",
        )
        self.assertEqual(
            self.helpers.map_pairing_error(Exception("unexpected"), "failed"),
            "pairing_failed",
        )

    def test_map_pairing_error_maps_state_based_token_and_confirmation_paths(self) -> None:
        for state in ("requesting_token", "token_received", "confirmed", "result_received"):
            self.assertEqual(
                self.helpers.map_pairing_error(Exception("n/a"), state),
                "pairing_token_timeout",
            )
        self.assertEqual(
            self.helpers.map_pairing_error(Exception("n/a"), "authenticated_pending_confirmation"),
            "pairing_confirm_after_auth_timeout",
        )

    def test_map_pairing_error_maps_authenticated_message_to_auth_failed(self) -> None:
        self.assertEqual(
            self.helpers.map_pairing_error(Exception("authenticated but rejected later"), ""),
            "auth_failed",
        )


class TestPairingNotificationText(unittest.TestCase):
    """Validate localized pairing notifications."""

    def setUp(self) -> None:
        self.helpers = _load_pairing_helpers()

    def test_german_waiting_message_mentions_device_confirmation(self) -> None:
        title, message = self.helpers.pairing_notification_text(
            "waiting_for_confirmation",
            "de",
        )

        self.assertEqual(title, "DHE-Pairing")
        self.assertIn("Bestätigung am Gerät", message)

    def test_english_waiting_message_mentions_device_only(self) -> None:
        _title, message = self.helpers.pairing_notification_text(
            "waiting_for_confirmation",
            "en",
        )

        self.assertIn("on the device", message)
        self.assertNotIn("web UI", message.casefold())


if __name__ == "__main__":
    unittest.main()
