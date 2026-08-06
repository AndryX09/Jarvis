import base64
import binascii
import hmac
import ipaddress
import logging
import os
import time
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs

import vault_core
from dashboard_auth import (
    create_session_token,
    load_totp_secret,
    matching_totp_counter,
    validate_session_token,
)
from dashboard_page import DASHBOARD_PAGE_HTML, LOGIN_PAGE_HTML
from dotenv import load_dotenv
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import (
    TransportSecurityMiddleware,
    TransportSecuritySettings,
)
from notes_page import NOTES_PAGE_HTML
from runtime_config import load_runtime_config
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from status_page import STATUS_PAGE_HTML
from vault_core import JarvisError

load_dotenv()

WEB_NOTE_RESPONSE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}
WEB_NOTE_PAGE_SIZE = 500
DASHBOARD_SESSION_COOKIE = "__Host-jarvis_dashboard_session"
DASHBOARD_SESSION_MAX_AGE_SECONDS = 28_800
DASHBOARD_LOGIN_MAX_FAILURES = 5
DASHBOARD_LOGIN_WINDOW_SECONDS = 300
DASHBOARD_LOGIN_MAX_CLIENTS = 2048
DASHBOARD_LOGIN_FAILURES: dict[str, list[float]] = {}
DASHBOARD_USED_TOTP_COUNTERS: set[int] = set()
DASHBOARD_RESPONSE_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
        "connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
}


class _RejectAllMcpTokens:
    async def verify_token(self, token: str) -> AccessToken | None:
        del token
        return None


def _load_web_note_password(path_text: str) -> bytes:
    path = Path(path_text)
    if path.is_symlink():
        raise ValueError("JARVIS_WEB_NOTE_PASSWORD_FILE must not be a symbolic link")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > 4096:
        raise ValueError("JARVIS_WEB_NOTE_PASSWORD_FILE must be a small regular file")
    password = resolved.read_bytes().rstrip(b"\r\n")
    if not password or b"\n" in password or b"\r" in password:
        raise ValueError("JARVIS_WEB_NOTE_PASSWORD_FILE must contain one password")
    if len(password) < 12:
        raise ValueError("JARVIS_WEB_NOTE_PASSWORD_FILE must contain at least 12 bytes")
    return password


def _authentication_required() -> Response:
    return Response(
        "Authentication required",
        status_code=401,
        headers={
            "WWW-Authenticate": 'Basic realm="Jarvis Notes", charset="UTF-8"',
            **WEB_NOTE_RESPONSE_HEADERS,
        },
    )


LOGGER = logging.getLogger(__name__)
VAULT_ROOT = vault_core.get_vault_root()
STATE_ROOT = vault_core.get_state_root()
RUNTIME_CONFIG = load_runtime_config(os.environ)
WEB_NOTE_PASSWORD = (
    _load_web_note_password(RUNTIME_CONFIG.web_note_password_file)
    if RUNTIME_CONFIG.web_note_scope != "none"
    else None
)
DASHBOARD_TOTP_SECRET = (
    load_totp_secret(RUNTIME_CONFIG.dashboard_totp_secret_file)
    if RUNTIME_CONFIG.dashboard_totp_secret_file
    else None
)
STATUS_TRANSPORT_SECURITY_SETTINGS = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=list(RUNTIME_CONFIG.allowed_hosts),
    allowed_origins=list(RUNTIME_CONFIG.allowed_origins),
)
MCP_TRANSPORT_SECURITY_SETTINGS = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=list(RUNTIME_CONFIG.mcp_allowed_hosts),
)
MCP_TOKEN_VERIFIER = None if RUNTIME_CONFIG.http_mcp_enabled else _RejectAllMcpTokens()
MCP_AUTH_SETTINGS = (
    None
    if RUNTIME_CONFIG.http_mcp_enabled
    else AuthSettings(
        issuer_url="http://127.0.0.1",
        resource_server_url=None,
        required_scopes=[],
    )
)
STATUS_ROUTE_SECURITY = TransportSecurityMiddleware(STATUS_TRANSPORT_SECURITY_SETTINGS)

mcp = FastMCP(
    "Jarvis Core v1.4.0",
    instructions=(
        "Personal Obsidian vault tools. Read operations are unrestricted inside visible "
        "Markdown notes. Mutations never delete notes, never overwrite a destination, "
        "create audit events, and preserve previous versions outside the vault. Before "
        "append, update, or move, call read_note and pass its sha256 as expected_sha256. "
        "Before restore_version, call both read_note and read_version and pass both hashes. "
        "For acquisition and triage, preserve the raw capture and call "
        "read_ingestion_policy. Triage changes capture states only; it does not create, "
        "update, or move notes. For conversation and note organization, call "
        "read_organization_policy and follow its confirmation rules. Capture state "
        "transitions are enforced by the server and require a fresh record_sha256 plus a "
        "non-empty summary. Mark a ready capture processed only after all referenced "
        "Markdown output notes exist. Ambiguous unreviewed material stays pending."
    ),
    host=RUNTIME_CONFIG.host,
    port=RUNTIME_CONFIG.port,
    streamable_http_path=RUNTIME_CONFIG.streamable_http_path,
    auth=MCP_AUTH_SETTINGS,
    token_verifier=MCP_TOKEN_VERIFIER,
    transport_security=MCP_TRANSPORT_SECURITY_SETTINGS,
)


def _safe(callable_, *args, **kwargs) -> dict[str, object]:
    try:
        return callable_(*args, **kwargs)
    except (JarvisError, OSError, UnicodeError) as exc:
        return {"error": str(exc)}


def _web_note_access_error(request: Request) -> Response | None:
    if WEB_NOTE_PASSWORD is None:
        return Response("Not Found", status_code=404, headers=WEB_NOTE_RESPONSE_HEADERS)
    authorization = request.headers.get("authorization", "")
    if len(authorization) > 8192:
        return _authentication_required()
    try:
        scheme, encoded = authorization.split(" ", 1)
        decoded = base64.b64decode(encoded, validate=True)
        username, separator, password = decoded.partition(b":")
    except (ValueError, binascii.Error):
        return _authentication_required()
    if (
        scheme.casefold() != "basic"
        or not separator
        or not hmac.compare_digest(username, b"jarvis")
        or not hmac.compare_digest(password, WEB_NOTE_PASSWORD)
    ):
        return _authentication_required()
    return None


def _web_note_path_allowed(path: str) -> bool:
    if RUNTIME_CONFIG.web_note_scope == "all-visible-markdown":
        return True
    if RUNTIME_CONFIG.web_note_scope == "panoramas":
        return path.rsplit("/", 1)[-1] == "00 — Panoramica.md"
    return False


def _dashboard_session_valid(request: Request) -> bool:
    if DASHBOARD_TOTP_SECRET is None:
        return False
    return validate_session_token(
        DASHBOARD_TOTP_SECRET,
        request.cookies.get(DASHBOARD_SESSION_COOKIE, ""),
        now=int(time.time()),
        max_age_seconds=DASHBOARD_SESSION_MAX_AGE_SECONDS,
    )


def _dashboard_login_key(request: Request) -> str:
    peer = request.client.host if request.client is not None else "unknown"
    if peer in RUNTIME_CONFIG.dashboard_trusted_proxy_peers:
        forwarded = request.headers.get("cf-connecting-ip", "")
        if forwarded and "," not in forwarded:
            try:
                client_ip = ipaddress.ip_address(forwarded.strip())
            except ValueError:
                pass
            else:
                return f"client:{client_ip.compressed}"
    return f"peer:{peer}"


def _dashboard_login_failures(key: str, now: float) -> list[float]:
    cutoff = now - DASHBOARD_LOGIN_WINDOW_SECONDS
    for existing_key, existing_failures in tuple(DASHBOARD_LOGIN_FAILURES.items()):
        current = [
            attempted_at for attempted_at in existing_failures if attempted_at >= cutoff
        ]
        if current:
            DASHBOARD_LOGIN_FAILURES[existing_key] = current
        else:
            DASHBOARD_LOGIN_FAILURES.pop(existing_key, None)
    return DASHBOARD_LOGIN_FAILURES.get(key, [])


def _record_dashboard_login_failure(key: str, now: float) -> None:
    failures = _dashboard_login_failures(key, now)
    DASHBOARD_LOGIN_FAILURES[key] = [*failures, now]
    overflow = len(DASHBOARD_LOGIN_FAILURES) - DASHBOARD_LOGIN_MAX_CLIENTS
    if overflow > 0:
        oldest_keys = sorted(
            DASHBOARD_LOGIN_FAILURES,
            key=lambda existing_key: DASHBOARD_LOGIN_FAILURES[existing_key][-1],
        )
        for existing_key in oldest_keys[:overflow]:
            DASHBOARD_LOGIN_FAILURES.pop(existing_key, None)


async def _read_limited_request_body(request: Request, max_bytes: int) -> bytes | None:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length, 10)
        except ValueError:
            return None
        if declared_length < 0 or declared_length > max_bytes:
            return None

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_bytes:
            return None
    return bytes(body)


@mcp.custom_route("/api/status", methods=["GET"])
async def status_api(request: Request) -> Response:
    """Return the same safe, read-only status data exposed by the MCP tool."""
    validation_error = await STATUS_ROUTE_SECURITY.validate_request(request)
    if validation_error is not None:
        return validation_error
    try:
        status = vault_core.vault_status(VAULT_ROOT, STATE_ROOT)
    except (JarvisError, OSError, UnicodeError):
        LOGGER.exception("Unable to collect Jarvis status for the public status API")
        return JSONResponse({"error": "Jarvis status unavailable"}, status_code=503)
    status["web_note_reading_available"] = WEB_NOTE_PASSWORD is not None
    status["dashboard_available"] = DASHBOARD_TOTP_SECRET is not None
    return JSONResponse(status)


@mcp.custom_route("/", methods=["GET"])
async def status_page(request: Request) -> Response:
    """Serve the dependency-free Jarvis Core status interface."""
    validation_error = await STATUS_ROUTE_SECURITY.validate_request(request)
    if validation_error is not None:
        return validation_error
    return HTMLResponse(STATUS_PAGE_HTML)


@mcp.custom_route("/dashboard", methods=["GET"])
async def dashboard_page(request: Request) -> Response:
    """Serve the authenticated, read-only Jarvis dashboard."""
    validation_error = await STATUS_ROUTE_SECURITY.validate_request(request)
    if validation_error is not None:
        return validation_error
    if DASHBOARD_TOTP_SECRET is None:
        return Response(
            "Not Found", status_code=404, headers=DASHBOARD_RESPONSE_HEADERS
        )
    if not _dashboard_session_valid(request):
        return RedirectResponse(
            "/login", status_code=303, headers=DASHBOARD_RESPONSE_HEADERS
        )
    return HTMLResponse(DASHBOARD_PAGE_HTML, headers=DASHBOARD_RESPONSE_HEADERS)


@mcp.custom_route("/api/dashboard/status", methods=["GET"])
async def dashboard_status_api(request: Request) -> Response:
    """Return allowlisted Jarvis process metadata to an authenticated session."""
    validation_error = await STATUS_ROUTE_SECURITY.validate_request(request)
    if validation_error is not None:
        return validation_error
    if DASHBOARD_TOTP_SECRET is None:
        return Response(
            "Not Found", status_code=404, headers=DASHBOARD_RESPONSE_HEADERS
        )
    if not _dashboard_session_valid(request):
        return JSONResponse(
            {"error": "Authentication required"},
            status_code=401,
            headers=DASHBOARD_RESPONSE_HEADERS,
        )
    raw_core: dict[str, object]
    raw_ingestion: dict[str, object]
    raw_activity: list[dict[str, object]]

    try:
        raw_core = vault_core.vault_status(VAULT_ROOT, STATE_ROOT)
        raw_ingestion = vault_core.ingestion_status(VAULT_ROOT, STATE_ROOT)
        raw_activity = cast(
            list[dict[str, object]],
            vault_core.recent_activity(STATE_ROOT, 20)["events"],
        )
    except (JarvisError, OSError, UnicodeError):
        LOGGER.exception("Unable to build the read-only dashboard status")
        return JSONResponse(
            {"error": "Jarvis dashboard unavailable"},
            status_code=503,
            headers=DASHBOARD_RESPONSE_HEADERS,
        )
    core_keys = (
        "service",
        "version",
        "vault_mode",
        "note_count",
        "audit_event_count",
        "ingestion_available",
        "delete_tool_available",
        "network_required",
    )
    capture_count_keys = ("total", "pending", "ready", "processed", "skipped")
    activity = [
        {key: event[key] for key in ("action", "timestamp_utc") if key in event}
        for event in raw_activity
        if isinstance(event, dict)
    ]
    return JSONResponse(
        {
            "core": {key: raw_core[key] for key in core_keys},
            "ingestion": {
                "captures": {
                    key: raw_ingestion["captures"][key] for key in capture_count_keys
                },
                "raw_material_is_preserved": raw_ingestion["raw_material_is_preserved"],
                "automatic_deletion_available": raw_ingestion[
                    "automatic_deletion_available"
                ],
            },
            "security": {
                "http_mcp_enabled": RUNTIME_CONFIG.http_mcp_enabled,
                "dashboard_mode": "read-only",
            },
            "activity": activity,
        },
        headers=DASHBOARD_RESPONSE_HEADERS,
    )


@mcp.custom_route("/login", methods=["GET", "POST"])
async def dashboard_login_page(request: Request) -> Response:
    """Serve the TOTP login form when the dashboard is enabled."""
    validation_error = await STATUS_ROUTE_SECURITY.validate_request(request)
    if validation_error is not None:
        return validation_error
    if DASHBOARD_TOTP_SECRET is None:
        return Response(
            "Not Found", status_code=404, headers=DASHBOARD_RESPONSE_HEADERS
        )
    if request.method == "GET":
        return HTMLResponse(LOGIN_PAGE_HTML, headers=DASHBOARD_RESPONSE_HEADERS)
    login_key = _dashboard_login_key(request)
    monotonic_now = time.monotonic()
    if (
        len(_dashboard_login_failures(login_key, monotonic_now))
        >= DASHBOARD_LOGIN_MAX_FAILURES
    ):
        return Response(
            "Too many attempts",
            status_code=429,
            headers={
                **DASHBOARD_RESPONSE_HEADERS,
                "Retry-After": str(DASHBOARD_LOGIN_WINDOW_SECONDS),
            },
        )
    if (
        not request.headers.get("content-type", "")
        .casefold()
        .startswith("application/x-www-form-urlencoded")
    ):
        _record_dashboard_login_failure(login_key, monotonic_now)
        return Response(
            "Invalid request", status_code=400, headers=DASHBOARD_RESPONSE_HEADERS
        )
    body = await _read_limited_request_body(request, 1024)
    if body is None:
        _record_dashboard_login_failure(login_key, monotonic_now)
        return Response(
            "Invalid request", status_code=400, headers=DASHBOARD_RESPONSE_HEADERS
        )
    try:
        fields = parse_qs(body.decode("ascii"), strict_parsing=True, max_num_fields=2)
        codes = fields["code"]
    except (KeyError, UnicodeDecodeError, ValueError):
        code = ""
    else:
        code = codes[0] if len(codes) == 1 else ""
    now = int(time.time())
    current_counter = now // 30
    DASHBOARD_USED_TOTP_COUNTERS.intersection_update(
        counter
        for counter in DASHBOARD_USED_TOTP_COUNTERS
        if counter >= current_counter - 1
    )
    matched_counter = matching_totp_counter(DASHBOARD_TOTP_SECRET, code, now=now)
    if matched_counter is None or matched_counter in DASHBOARD_USED_TOTP_COUNTERS:
        _record_dashboard_login_failure(login_key, monotonic_now)
        return HTMLResponse(
            LOGIN_PAGE_HTML, status_code=401, headers=DASHBOARD_RESPONSE_HEADERS
        )
    DASHBOARD_USED_TOTP_COUNTERS.add(matched_counter)
    DASHBOARD_LOGIN_FAILURES.pop(login_key, None)
    response = RedirectResponse(
        "/dashboard", status_code=303, headers=DASHBOARD_RESPONSE_HEADERS
    )
    response.set_cookie(
        DASHBOARD_SESSION_COOKIE,
        create_session_token(DASHBOARD_TOTP_SECRET, now=now),
        max_age=DASHBOARD_SESSION_MAX_AGE_SECONDS,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return response


@mcp.custom_route("/logout", methods=["POST"])
async def dashboard_logout(request: Request) -> Response:
    """Clear the dashboard session cookie without mutating Jarvis state."""
    validation_error = await STATUS_ROUTE_SECURITY.validate_request(request)
    if validation_error is not None:
        return validation_error
    if DASHBOARD_TOTP_SECRET is None:
        return Response(
            "Not Found", status_code=404, headers=DASHBOARD_RESPONSE_HEADERS
        )
    response = RedirectResponse(
        "/login", status_code=303, headers=DASHBOARD_RESPONSE_HEADERS
    )
    response.delete_cookie(
        DASHBOARD_SESSION_COOKIE,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return response


@mcp.custom_route("/notes", methods=["GET"])
async def notes_page(request: Request) -> Response:
    """Serve the password-protected, read-only note browser."""
    validation_error = await STATUS_ROUTE_SECURITY.validate_request(request)
    if validation_error is not None:
        return validation_error
    access_error = _web_note_access_error(request)
    if access_error is not None:
        return access_error
    return HTMLResponse(
        NOTES_PAGE_HTML,
        headers=WEB_NOTE_RESPONSE_HEADERS,
    )


@mcp.custom_route("/api/notes", methods=["GET"])
async def notes_api(request: Request) -> Response:
    """List only the visible Markdown notes enabled for web reading."""
    validation_error = await STATUS_ROUTE_SECURITY.validate_request(request)
    if validation_error is not None:
        return validation_error
    access_error = _web_note_access_error(request)
    if access_error is not None:
        return access_error
    raw_offset = request.query_params.get("offset", "0")
    try:
        offset = int(raw_offset)
    except ValueError:
        offset = -1
    if offset < 0 or str(offset) != raw_offset:
        return JSONResponse(
            {"error": "Invalid note-list offset"},
            status_code=400,
            headers=WEB_NOTE_RESPONSE_HEADERS,
        )
    try:
        filename = (
            "00 — Panoramica.md"
            if RUNTIME_CONFIG.web_note_scope == "panoramas"
            else None
        )
        listed = vault_core.list_notes_in_vault(
            VAULT_ROOT,
            "",
            WEB_NOTE_PAGE_SIZE,
            offset=offset,
            filename=filename,
        )
        notes = [
            note
            for note in listed["notes"]
            if _web_note_path_allowed(str(note["path"]))
        ]
    except (JarvisError, OSError, UnicodeError):
        LOGGER.exception("Unable to list notes for the protected web interface")
        return JSONResponse(
            {"error": "Note list unavailable"},
            status_code=503,
            headers=WEB_NOTE_RESPONSE_HEADERS,
        )
    return JSONResponse(
        {
            "scope": RUNTIME_CONFIG.web_note_scope,
            "notes": notes,
            "page_size": WEB_NOTE_PAGE_SIZE,
            "offset": offset,
            "next_offset": offset + len(notes) if listed["limit_reached"] else None,
        },
        headers=WEB_NOTE_RESPONSE_HEADERS,
    )


@mcp.custom_route("/api/note", methods=["GET"])
async def note_api(request: Request) -> Response:
    """Read one password-protected note when the configured scope permits it."""
    validation_error = await STATUS_ROUTE_SECURITY.validate_request(request)
    if validation_error is not None:
        return validation_error
    access_error = _web_note_access_error(request)
    if access_error is not None:
        return access_error
    path = request.query_params.get("path", "")
    if not _web_note_path_allowed(path):
        return Response(
            "Note not available", status_code=404, headers=WEB_NOTE_RESPONSE_HEADERS
        )
    try:
        note = vault_core.read_note_from_vault(VAULT_ROOT, path)
    except JarvisError:
        return Response(
            "Note not available", status_code=404, headers=WEB_NOTE_RESPONSE_HEADERS
        )
    except (OSError, UnicodeError):
        LOGGER.exception("Unable to read a note for the protected web interface")
        return JSONResponse(
            {"error": "Note unavailable"},
            status_code=503,
            headers=WEB_NOTE_RESPONSE_HEADERS,
        )
    return JSONResponse(
        {
            "path": note["path"],
            "size_bytes": note["size_bytes"],
            "modified_utc": note["modified_utc"],
            "content": note["content"],
        },
        headers=WEB_NOTE_RESPONSE_HEADERS,
    )


@mcp.tool()
def jarvis_status() -> dict[str, object]:
    """Show Jarvis Core version, vault mode, note count, and safety capabilities."""
    return _safe(vault_core.vault_status, VAULT_ROOT, STATE_ROOT)


@mcp.tool()
def list_notes(folder: str = "", max_results: int = 100) -> dict[str, object]:
    """List visible Markdown notes in the vault or one vault-relative folder."""
    return _safe(vault_core.list_notes_in_vault, VAULT_ROOT, folder, max_results)


@mcp.tool()
def search_notes(query: str, max_results: int = 20) -> dict[str, object]:
    """Search visible Markdown notes for literal case-insensitive text."""
    return _safe(vault_core.search_vault, VAULT_ROOT, query, max_results)


@mcp.tool()
def read_note(path: str) -> dict[str, object]:
    """Read one Markdown note and return its content and sha256 revision token."""
    return _safe(vault_core.read_note_from_vault, VAULT_ROOT, path)


@mcp.tool()
def list_versions(path: str, max_results: int = 20) -> dict[str, object]:
    """List saved versions of one note without returning their contents."""
    return _safe(vault_core.list_note_versions, STATE_ROOT, path, max_results)


@mcp.tool()
def read_version(path: str, version_id: str) -> dict[str, object]:
    """Read one saved version and return its content and sha256 verification token."""
    return _safe(vault_core.read_note_version, STATE_ROOT, path, version_id)


@mcp.tool()
def list_tasks(max_results: int = 100) -> dict[str, object]:
    """List unchecked Markdown tasks from visible notes."""
    return _safe(vault_core.list_tasks_in_vault, VAULT_ROOT, max_results)


@mcp.tool()
def recent_notes(max_results: int = 20) -> dict[str, object]:
    """List the most recently modified visible Markdown notes."""
    return _safe(vault_core.recent_notes, VAULT_ROOT, max_results)


@mcp.tool()
def ingestion_status() -> dict[str, object]:
    """Show capture counts and whether the acquisition and triage policy is available."""
    return _safe(vault_core.ingestion_status, VAULT_ROOT, STATE_ROOT)


@mcp.tool()
def read_ingestion_policy() -> dict[str, object]:
    """Read the user-authored rules for acquisition, triage, and capture states."""
    return _safe(vault_core.read_ingestion_policy, VAULT_ROOT)


@mcp.tool()
def read_organization_policy() -> dict[str, object]:
    """Read the user-authored rules for conversation and note organization."""
    return _safe(vault_core.read_organization_policy, VAULT_ROOT)


@mcp.tool()
def capture_material(
    title: str,
    content: str,
    source_kind: str = "manual",
    source_ref: str = "",
    labels: list[str] | None = None,
    source_created_utc: str = "",
    source_updated_utc: str = "",
) -> dict[str, object]:
    """Preserve raw text in the ingestion queue; exact duplicates are not stored twice."""
    return _safe(
        vault_core.capture_material,
        STATE_ROOT,
        title,
        content,
        source_kind,
        source_ref,
        labels,
        source_created_utc,
        source_updated_utc,
    )


@mcp.tool()
def list_captures(status: str = "pending", max_results: int = 20) -> dict[str, object]:
    """List capture metadata without returning the raw content."""
    return _safe(vault_core.list_captures, STATE_ROOT, status, max_results)


@mcp.tool()
def read_capture(capture_id: str) -> dict[str, object]:
    """Read one preserved capture and return its record_sha256 revision token."""
    return _safe(vault_core.read_capture, STATE_ROOT, capture_id)


@mcp.tool()
def read_pending_captures(max_results: int = 10) -> dict[str, object]:
    """Read up to 20 pending captures for bounded batch triage without changing them."""
    return _safe(vault_core.read_pending_captures, STATE_ROOT, max_results)


@mcp.tool()
def update_capture_status(
    capture_id: str,
    status: str,
    expected_record_sha256: str,
    summary: str,
    output_paths: list[str] | None = None,
) -> dict[str, object]:
    """Apply an allowed capture-state transition with fresh hash and non-empty summary."""
    return _safe(
        vault_core.update_capture_status,
        VAULT_ROOT,
        STATE_ROOT,
        capture_id,
        status,
        expected_record_sha256,
        output_paths,
        summary,
    )


@mcp.tool()
def create_note(path: str, content: str) -> dict[str, object]:
    """Create a new Markdown note. Existing files are never overwritten."""
    return _safe(vault_core.create_note_in_vault, VAULT_ROOT, STATE_ROOT, path, content)


@mcp.tool()
def create_inbox_note(title: str, content: str) -> dict[str, object]:
    """Create a timestamped note in the dedicated AI Inbox folder."""
    return _safe(vault_core.create_inbox_note, VAULT_ROOT, STATE_ROOT, title, content)


@mcp.tool()
def append_to_note(path: str, content: str, expected_sha256: str) -> dict[str, object]:
    """Append text after verifying the sha256 returned by a fresh read_note call."""
    return _safe(
        vault_core.append_to_note_in_vault,
        VAULT_ROOT,
        STATE_ROOT,
        path,
        content,
        expected_sha256,
    )


@mcp.tool()
def update_note(path: str, content: str, expected_sha256: str) -> dict[str, object]:
    """Replace one note after revision verification and preserve its previous version."""
    return _safe(
        vault_core.update_note_in_vault,
        VAULT_ROOT,
        STATE_ROOT,
        path,
        content,
        expected_sha256,
    )


@mcp.tool()
def restore_version(
    path: str,
    version_id: str,
    expected_sha256: str,
    expected_version_sha256: str,
) -> dict[str, object]:
    """Restore a saved version after verifying both current and saved revision hashes."""
    return _safe(
        vault_core.restore_note_version,
        VAULT_ROOT,
        STATE_ROOT,
        path,
        version_id,
        expected_sha256,
        expected_version_sha256,
    )


@mcp.tool()
def move_note(
    source_path: str, destination_path: str, expected_sha256: str
) -> dict[str, object]:
    """Move a note inside the vault without overwriting an existing destination."""
    return _safe(
        vault_core.move_note_in_vault,
        VAULT_ROOT,
        STATE_ROOT,
        source_path,
        destination_path,
        expected_sha256,
    )


@mcp.tool()
def recent_activity(max_results: int = 20) -> dict[str, object]:
    """Return recent mutation audit metadata without note contents."""
    return _safe(vault_core.recent_activity, STATE_ROOT, max_results)


def run_server() -> None:
    if RUNTIME_CONFIG.transport != "streamable-http":
        mcp.run(transport=RUNTIME_CONFIG.transport)
        return

    import uvicorn

    config = uvicorn.Config(
        mcp.streamable_http_app(),
        host=RUNTIME_CONFIG.host,
        port=RUNTIME_CONFIG.port,
        log_level=mcp.settings.log_level.lower(),
        proxy_headers=False,
    )
    uvicorn.Server(config).run()


if __name__ == "__main__":
    run_server()
