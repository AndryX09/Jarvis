from __future__ import annotations

import hmac
import os
import re
import stat

from mcp.server.auth.provider import AccessToken


MCP_BEARER_TOKEN_MAX_BYTES = 512
_BEARER_TOKEN_PATTERN = re.compile(rb"[A-Za-z0-9._~+/=-]+")


class StaticBearerTokenVerifier:
    def __init__(self, expected_token: bytes):
        self._expected_token = expected_token

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            candidate = token.encode("ascii")
        except UnicodeEncodeError:
            return None
        if not hmac.compare_digest(candidate, self._expected_token):
            return None
        return AccessToken(
            token=token,
            client_id="jarvis-hermes-client",
            scopes=[],
        )


def load_mcp_bearer_token(path_text: str) -> bytes:
    original = os.lstat(path_text)
    if stat.S_ISLNK(original.st_mode):
        raise ValueError("JARVIS_MCP_BEARER_TOKEN_FILE must not be a symbolic link")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path_text, flags)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_size > MCP_BEARER_TOKEN_MAX_BYTES
        ):
            raise ValueError(
                "JARVIS_MCP_BEARER_TOKEN_FILE must be a small regular file"
            )
        if (opened.st_dev, opened.st_ino) != (original.st_dev, original.st_ino):
            raise ValueError("JARVIS_MCP_BEARER_TOKEN_FILE changed during load")

        content = bytearray()
        while len(content) <= MCP_BEARER_TOKEN_MAX_BYTES:
            chunk = os.read(
                descriptor,
                MCP_BEARER_TOKEN_MAX_BYTES + 1 - len(content),
            )
            if not chunk:
                break
            content.extend(chunk)
        if len(content) > MCP_BEARER_TOKEN_MAX_BYTES:
            raise ValueError(
                "JARVIS_MCP_BEARER_TOKEN_FILE must be a small regular file"
            )
        finished = os.fstat(descriptor)
        if (
            finished.st_size != opened.st_size
            or finished.st_mtime_ns != opened.st_mtime_ns
        ):
            raise ValueError("JARVIS_MCP_BEARER_TOKEN_FILE changed during load")
    finally:
        os.close(descriptor)

    token = bytes(content).rstrip(b"\r\n")
    if b"\n" in token or b"\r" in token:
        raise ValueError("JARVIS_MCP_BEARER_TOKEN_FILE must contain one token")
    if len(token) < 32:
        raise ValueError(
            "JARVIS_MCP_BEARER_TOKEN_FILE must contain at least 32 bytes"
        )
    if _BEARER_TOKEN_PATTERN.fullmatch(token) is None:
        raise ValueError(
            "JARVIS_MCP_BEARER_TOKEN_FILE contains invalid Bearer token bytes"
        )
    return token
