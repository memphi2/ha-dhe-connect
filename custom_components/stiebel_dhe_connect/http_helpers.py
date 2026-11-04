"""Bounded reads for the device's uncompressed local HTTP protocol."""

from __future__ import annotations

import aiohttp

from .client_types import DHEError

PROTOCOL_RESPONSE_LIMIT = 4 * 1024 * 1024
WEB_PAGE_RESPONSE_LIMIT = 256 * 1024
IDENTITY_ENCODING_HEADERS = {"Accept-Encoding": "identity"}


async def read_bounded_response(response: aiohttp.ClientResponse, limit: int) -> bytes:
    """Read at most limit bytes, without trusting length or compressed metadata.

    Callers disable aiohttp auto-decompression and request identity encoding so
    decompression cannot allocate an unbounded body before this check runs.
    """
    if response.headers.get("Content-Encoding", "identity").strip().lower() != "identity":
        raise DHEError("Compressed DHE response refused")
    if response.content_length is not None and response.content_length > limit:
        raise DHEError("DHE response exceeds size limit")
    body = bytearray()
    async for chunk in response.content.iter_chunked(64 * 1024):
        if len(body) + len(chunk) > limit:
            raise DHEError("DHE response exceeds size limit")
        body.extend(chunk)
    return bytes(body)
