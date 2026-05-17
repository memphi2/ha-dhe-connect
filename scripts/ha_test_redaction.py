"""Redaction helpers for HA test scripts."""

from __future__ import annotations

import re


SECRET_VALUE_RE = re.compile(
    r"(?i)(access_token|refresh_token|authorization|password|code)"
    r"([\"'\s:=]+)"
    r"([^\"'\s,&)}\]]+)"
)
BEARER_TOKEN_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
URL_CREDENTIAL_RE = re.compile(r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@")
PRIVATE_HOST_RE = re.compile(
    r"(?<![0-9])(?:10|172\.(?:1[6-9]|2[0-9]|3[0-1])|192\.168)"
    r"(?:\.[0-9]{1,3}){2}(?::[0-9]+)?(?![0-9])"
)


def redact_sensitive_text(value: object) -> str:
    """Return a string safe enough for test-script console output."""
    text = str(value)
    text = BEARER_TOKEN_RE.sub("Bearer <redacted>", text)
    text = URL_CREDENTIAL_RE.sub(r"\1<redacted>@", text)
    text = SECRET_VALUE_RE.sub(r"\1\2<redacted>", text)
    return PRIVATE_HOST_RE.sub("<private-host>", text)


def format_redacted_exception(err: BaseException) -> str:
    """Return a redacted exception class and message."""
    return f"{type(err).__name__}: {redact_sensitive_text(err)}"
