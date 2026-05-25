"""Tests for the repository privacy-marker guard."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts import check_privacy_markers


class TestCheckPrivacyMarkers(unittest.TestCase):
    """Validate privacy-marker guard behavior on synthetic files."""

    def test_accepts_clean_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "clean.md"
            path.write_text(
                "Use docs examples with TEST-NET addresses like 192.0.2.10.\n",
                encoding="utf-8",
            )
            self.assertEqual(check_privacy_markers.find_privacy_issues([path]), [])

    def test_rejects_non_placeholder_username(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "username.md"
            key = "HA_TEST_USERNAME"
            value = "-".join(("real", "user"))
            path.write_text(f"{key}={value}\n", encoding="utf-8")
            issues = check_privacy_markers.find_privacy_issues([path])
            self.assertEqual(len(issues), 1)
            self.assertIn("HA_TEST_USERNAME", issues[0])

    def test_accepts_quoted_placeholder_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "placeholders.md"
            path.write_text(
                (
                    "HA_TEST_USERNAME=\"your-ha-user\"\n"
                    "HA_TEST_PASSWORD='your-ha-password'\n"
                ),
                encoding="utf-8",
            )
            issues = check_privacy_markers.find_privacy_issues([path])
            self.assertEqual(issues, [])

    def test_rejects_private_ip_test_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ip.md"
            key = "HA_TEST_URL"
            host = ".".join(("10", "23", "45", "67"))
            path.write_text(f"{key}=http://{host}:8123\n", encoding="utf-8")
            issues = check_privacy_markers.find_privacy_issues([path])
            self.assertEqual(len(issues), 1)
            self.assertIn("private-IP HA_TEST_URL", issues[0])

    def test_rejects_jwt_like_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "token.md"
            token = ".".join(
                (
                    "eyJ" + "hbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
                    "eyJpc3MiOiIxMjM0NTY3ODkwIiwiaWF0IjoxNzAwMDAwMDAwfQ",
                    "A1234567890BCDEFGHIJKLMNOPQRSTUVWX",
                )
            )
            path.write_text(
                f"{token}\n",
                encoding="utf-8",
            )
            issues = check_privacy_markers.find_privacy_issues([path])
            self.assertEqual(len(issues), 1)
            self.assertIn("JWT-like token", issues[0])


if __name__ == "__main__":
    unittest.main()
