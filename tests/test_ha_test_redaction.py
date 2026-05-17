"""Tests for HA test-script redaction helpers."""

from __future__ import annotations

import unittest

from scripts.ha_test_redaction import redact_sensitive_text


class TestHATestRedaction(unittest.TestCase):
    """Validate console-output redaction used by HA smoke helpers."""

    def test_redacts_tokenized_urls_and_auth_context(self) -> None:
        private_host = ".".join(("172", "16", "1", "147"))
        text = redact_sensitive_text(
            f"http://user:secret@{private_host}:8123/path?token=abc123 "
            "access_token=def456 Authorization: Bearer ghijk password=secret"
        )

        self.assertIn("<redacted>", text)
        self.assertIn("<private-host>", text)
        self.assertNotIn("abc123", text)
        self.assertNotIn("def456", text)
        self.assertNotIn("ghijk", text)
        self.assertNotIn("secret", text)
        self.assertNotIn(private_host, text)

    def test_redacts_full_private_ten_host(self) -> None:
        private_host = ".".join(("10", "0", "0", "1"))
        text = redact_sensitive_text(f"http://{private_host}:8123/path")

        self.assertEqual(text, "http://<private-host>/path")
        self.assertNotIn(private_host, text)
        self.assertNotIn(".1", text)

    def test_redacts_space_separated_secret_arguments(self) -> None:
        text = redact_sensitive_text(
            "--password secret --access_token 'abc' --code \"quoted\" "
            "password 123456 access_token 'abc123' code 123456 "
            "password secret code alpha authorization abc123 "
            "authorization 'quoted-auth'"
        )

        self.assertEqual(
            text,
            "--password <redacted> --access_token '<redacted>' "
            "--code \"<redacted>\" password <redacted> "
            "access_token '<redacted>' code <redacted> password <redacted> "
            "code <redacted> authorization <redacted> "
            "authorization '<redacted>'",
        )
        self.assertNotIn("secret", text)
        self.assertNotIn("alpha", text)
        self.assertNotIn("abc", text)
        self.assertNotIn("abc123", text)
        self.assertNotIn("123456", text)
        self.assertNotIn("quoted", text)
        self.assertNotIn("quoted-auth", text)

    def test_preserves_ordinary_text(self) -> None:
        text = redact_sensitive_text("code blue station and password reset forecast")

        self.assertEqual(text, "code blue station and password reset forecast")


if __name__ == "__main__":
    unittest.main()
