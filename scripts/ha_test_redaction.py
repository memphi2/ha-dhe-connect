"""Redaction helpers for HA test scripts."""

from __future__ import annotations

import re


SECRET_VALUE_RE = re.compile(
    r"(?i)(access_token|refresh_token|password|code)"
    r"([\"']?\s*[:=]\s*[\"']?)"
    r"([^\"'\s,&)}\]]+)"
    r"([\"']?)"
)
SECRET_OPTION_RE = re.compile(
    r"(?i)(--(?:access[_-]?token|refresh[_-]?token|password|code)\s+)"
    r"([\"']?)"
    r"([^\"'\s,&)}\]]+)"
    r"([\"']?)"
)
TOKEN_WHITESPACE_RE = re.compile(
    r"(?i)\b(access_token|refresh_token)"
    r"(\s+)"
    r"([\"']?)"
    r"([^\"'\s,&)}\]]+)"
    r"([\"']?)"
)
TOKENISH_WHITESPACE_RE = re.compile(
    r"(?i)\b(password|code)"
    r"(\s+)"
    r"([\"']?)"
    r"(?!(?:reset|blue)\b)"
    r"([^\"'\s,&)}\]]+)"
    r"([\"']?)"
)
AUTHORIZATION_FIELD_RE = re.compile(
    r"(?i)(authorization)"
    r"([\"']?\s*(?::|=|\s)\s*[\"']?)"
    r"(?!Bearer\b)"
    r"([^\"'\s,&)}\]]+)"
    r"([\"']?)"
)
BEARER_TOKEN_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
TOKEN_QUERY_RE = re.compile(
    r"(?i)([?&](?:access_token|refresh_token|token|code)=)[^&\s]+"
)
URL_CREDENTIAL_RE = re.compile(r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@")
PRIVATE_HOST_RE = re.compile(
    r"(?<![0-9])(?:"
    r"10(?:\.[0-9]{1,3}){3}|"
    r"172\.(?:1[6-9]|2[0-9]|3[0-1])(?:\.[0-9]{1,3}){2}|"
    r"192\.168(?:\.[0-9]{1,3}){2}"
    r")(?::[0-9]+)?(?![0-9])"
)


def redact_sensitive_text(value: object) -> str:
    """Return a string safe enough for test-script console output."""
    text = str(value)
    text = BEARER_TOKEN_RE.sub("Bearer <redacted>", text)
    text = URL_CREDENTIAL_RE.sub(r"\1<redacted>@", text)
    text = TOKEN_QUERY_RE.sub(r"\1<redacted>", text)
    text = SECRET_VALUE_RE.sub(r"\1\2<redacted>\4", text)
    text = SECRET_OPTION_RE.sub(r"\1\2<redacted>\4", text)
    text = TOKEN_WHITESPACE_RE.sub(r"\1\2\3<redacted>\5", text)
    text = TOKENISH_WHITESPACE_RE.sub(r"\1\2\3<redacted>\5", text)
    text = AUTHORIZATION_FIELD_RE.sub(r"\1\2<redacted>\4", text)
    return PRIVATE_HOST_RE.sub("<private-host>", text)


def format_redacted_exception(err: BaseException) -> str:
    """Return a redacted exception class and message."""
    return f"{type(err).__name__}: {redact_sensitive_text(err)}"
