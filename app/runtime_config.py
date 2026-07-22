from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class RuntimeConfig:
    transport: str
    host: str
    port: int
    streamable_http_path: str
    allowed_hosts: tuple[str, ...]


def load_runtime_config(environ: Mapping[str, str]) -> RuntimeConfig:
    transport = environ.get("JARVIS_TRANSPORT", "stdio")
    if transport not in {"stdio", "streamable-http"}:
        raise ValueError(
            "JARVIS_TRANSPORT must be 'stdio' or 'streamable-http'"
        )
    raw_port = environ.get("JARVIS_HTTP_PORT", "8000")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("JARVIS_HTTP_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("JARVIS_HTTP_PORT must be between 1 and 65535")
    allowed_hosts = tuple(
        value.strip()
        for value in environ.get(
            "JARVIS_HTTP_ALLOWED_HOSTS", "127.0.0.1:*,localhost:*"
        ).split(",")
        if value.strip()
    )
    if transport == "streamable-http" and not allowed_hosts:
        raise ValueError(
            "JARVIS_HTTP_ALLOWED_HOSTS must not be empty for streamable-http"
        )
    return RuntimeConfig(
        transport=transport,
        host=environ.get("JARVIS_HTTP_HOST", "127.0.0.1"),
        port=port,
        streamable_http_path="/mcp",
        allowed_hosts=allowed_hosts,
    )
