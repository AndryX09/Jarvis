from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from typing import Mapping
from urllib.parse import urlsplit


@dataclass(frozen=True)
class RuntimeConfig:
    transport: str
    host: str
    port: int
    streamable_http_path: str
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]
    mcp_allowed_hosts: tuple[str, ...]
    http_mcp_enabled: bool
    mcp_bearer_token_file: str
    dashboard_totp_secret_file: str
    dashboard_trusted_proxy_peers: tuple[str, ...]
    web_note_scope: str
    web_note_password_file: str


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
    allowed_origins = tuple(
        value.strip()
        for value in environ.get(
            "JARVIS_HTTP_ALLOWED_ORIGINS",
            "http://127.0.0.1:*,http://localhost:*",
        ).split(",")
        if value.strip()
    )
    if transport == "streamable-http" and not allowed_origins:
        raise ValueError(
            "JARVIS_HTTP_ALLOWED_ORIGINS must not be empty for streamable-http"
        )
    for origin in allowed_origins:
        parsed = urlsplit(origin[:-2] if origin.endswith(":*") else origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("JARVIS_HTTP_ALLOWED_ORIGINS contains an invalid origin")
    mcp_allowed_hosts = tuple(
        value.strip()
        for value in environ.get(
            "JARVIS_MCP_ALLOWED_HOSTS", "127.0.0.1:*,localhost:*"
        ).split(",")
        if value.strip()
    )
    if transport == "streamable-http" and not mcp_allowed_hosts:
        raise ValueError(
            "JARVIS_MCP_ALLOWED_HOSTS must not be empty for streamable-http"
        )
    raw_http_mcp_enabled = (
        environ.get("JARVIS_HTTP_MCP_ENABLED", "false").strip().casefold()
    )
    if raw_http_mcp_enabled not in {"true", "false"}:
        raise ValueError("JARVIS_HTTP_MCP_ENABLED must be 'true' or 'false'")
    http_mcp_enabled = raw_http_mcp_enabled == "true"
    mcp_bearer_token_file = environ.get(
        "JARVIS_MCP_BEARER_TOKEN_FILE", ""
    ).strip()
    if http_mcp_enabled and not mcp_bearer_token_file:
        raise ValueError(
            "JARVIS_MCP_BEARER_TOKEN_FILE is required when HTTP MCP is enabled"
        )
    dashboard_totp_secret_file = environ.get(
        "JARVIS_DASHBOARD_TOTP_SECRET_FILE", ""
    ).strip()
    dashboard_trusted_proxy_peers = tuple(
        value.strip()
        for value in environ.get(
            "JARVIS_DASHBOARD_TRUSTED_PROXY_PEERS", ""
        ).split(",")
        if value.strip()
    )
    for peer in dashboard_trusted_proxy_peers:
        try:
            ipaddress.ip_address(peer)
        except ValueError as exc:
            raise ValueError(
                "JARVIS_DASHBOARD_TRUSTED_PROXY_PEERS must contain IP addresses"
            ) from exc
    web_note_scope = environ.get("JARVIS_WEB_NOTE_SCOPE", "none")
    if web_note_scope not in {"none", "panoramas", "all-visible-markdown"}:
        raise ValueError(
            "JARVIS_WEB_NOTE_SCOPE must be 'none', 'panoramas', or "
            "'all-visible-markdown'"
        )
    web_note_password_file = environ.get("JARVIS_WEB_NOTE_PASSWORD_FILE", "").strip()
    if web_note_scope != "none" and not web_note_password_file:
        raise ValueError(
            "JARVIS_WEB_NOTE_PASSWORD_FILE is required when web note reading is enabled"
        )
    return RuntimeConfig(
        transport=transport,
        host=environ.get("JARVIS_HTTP_HOST", "127.0.0.1"),
        port=port,
        streamable_http_path="/mcp",
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
        mcp_allowed_hosts=mcp_allowed_hosts,
        http_mcp_enabled=http_mcp_enabled,
        mcp_bearer_token_file=mcp_bearer_token_file,
        dashboard_totp_secret_file=dashboard_totp_secret_file,
        dashboard_trusted_proxy_peers=dashboard_trusted_proxy_peers,
        web_note_scope=web_note_scope,
        web_note_password_file=web_note_password_file,
    )
