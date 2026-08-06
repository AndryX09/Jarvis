import base64
import binascii
import hmac
import logging
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import (
    TransportSecurityMiddleware,
    TransportSecuritySettings,
)
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from notes_page import NOTES_PAGE_HTML
from runtime_config import load_runtime_config
from status_page import STATUS_PAGE_HTML

from vault_core import (
    JarvisError,
    append_to_note_in_vault,
    capture_material as capture_material_in_state,
    create_inbox_note as create_inbox_note_in_vault,
    create_note_in_vault,
    get_state_root,
    get_vault_root,
    ingestion_status as get_ingestion_status,
    list_captures as list_captures_in_state,
    list_notes_in_vault,
    list_note_versions,
    list_tasks_in_vault,
    move_note_in_vault,
    read_capture as read_capture_from_state,
    read_pending_captures as read_pending_captures_from_state,
    read_ingestion_policy as read_ingestion_policy_from_vault,
    read_organization_policy as read_organization_policy_from_vault,
    read_note_from_vault,
    read_note_version,
    recent_activity as get_recent_activity,
    recent_notes as get_recent_notes,
    restore_note_version,
    search_vault,
    update_note_in_vault,
    update_capture_status as update_capture_status_in_state,
    vault_status as get_vault_status,
)


WEB_NOTE_RESPONSE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}
WEB_NOTE_PAGE_SIZE = 500


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
VAULT_ROOT = get_vault_root()
STATE_ROOT = get_state_root()
RUNTIME_CONFIG = load_runtime_config(os.environ)
WEB_NOTE_PASSWORD = (
    _load_web_note_password(RUNTIME_CONFIG.web_note_password_file)
    if RUNTIME_CONFIG.web_note_scope != "none"
    else None
)
STATUS_TRANSPORT_SECURITY_SETTINGS = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=list(RUNTIME_CONFIG.allowed_hosts),
)
MCP_TRANSPORT_SECURITY_SETTINGS = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=list(RUNTIME_CONFIG.mcp_allowed_hosts),
)
MCP_TOKEN_VERIFIER = (
    None if RUNTIME_CONFIG.http_mcp_enabled else _RejectAllMcpTokens()
)
MCP_AUTH_SETTINGS = (
    None
    if RUNTIME_CONFIG.http_mcp_enabled
    else AuthSettings(
        issuer_url="http://127.0.0.1",
        resource_server_url=None,
        required_scopes=[],
    )
)
STATUS_ROUTE_SECURITY = TransportSecurityMiddleware(
    STATUS_TRANSPORT_SECURITY_SETTINGS
)

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
        return Response(
            "Not Found", status_code=404, headers=WEB_NOTE_RESPONSE_HEADERS
        )
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


@mcp.custom_route("/api/status", methods=["GET"])
async def status_api(request: Request) -> Response:
    """Return the same safe, read-only status data exposed by the MCP tool."""
    validation_error = await STATUS_ROUTE_SECURITY.validate_request(request)
    if validation_error is not None:
        return validation_error
    try:
        status = get_vault_status(VAULT_ROOT, STATE_ROOT)
    except (JarvisError, OSError, UnicodeError):
        LOGGER.exception("Unable to collect Jarvis status for the public status API")
        return JSONResponse({"error": "Jarvis status unavailable"}, status_code=503)
    status["web_note_reading_available"] = WEB_NOTE_PASSWORD is not None
    return JSONResponse(status)


@mcp.custom_route("/", methods=["GET"])
async def status_page(request: Request) -> Response:
    """Serve the dependency-free Jarvis Core status interface."""
    validation_error = await STATUS_ROUTE_SECURITY.validate_request(request)
    if validation_error is not None:
        return validation_error
    return HTMLResponse(STATUS_PAGE_HTML)


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
        listed = list_notes_in_vault(
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
        note = read_note_from_vault(VAULT_ROOT, path)
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
    return _safe(get_vault_status, VAULT_ROOT, STATE_ROOT)


@mcp.tool()
def list_notes(folder: str = "", max_results: int = 100) -> dict[str, object]:
    """List visible Markdown notes in the vault or one vault-relative folder."""
    return _safe(list_notes_in_vault, VAULT_ROOT, folder, max_results)


@mcp.tool()
def search_notes(query: str, max_results: int = 20) -> dict[str, object]:
    """Search visible Markdown notes for literal case-insensitive text."""
    return _safe(search_vault, VAULT_ROOT, query, max_results)


@mcp.tool()
def read_note(path: str) -> dict[str, object]:
    """Read one Markdown note and return its content and sha256 revision token."""
    return _safe(read_note_from_vault, VAULT_ROOT, path)


@mcp.tool()
def list_versions(path: str, max_results: int = 20) -> dict[str, object]:
    """List saved versions of one note without returning their contents."""
    return _safe(list_note_versions, STATE_ROOT, path, max_results)


@mcp.tool()
def read_version(path: str, version_id: str) -> dict[str, object]:
    """Read one saved version and return its content and sha256 verification token."""
    return _safe(read_note_version, STATE_ROOT, path, version_id)


@mcp.tool()
def list_tasks(max_results: int = 100) -> dict[str, object]:
    """List unchecked Markdown tasks from visible notes."""
    return _safe(list_tasks_in_vault, VAULT_ROOT, max_results)


@mcp.tool()
def recent_notes(max_results: int = 20) -> dict[str, object]:
    """List the most recently modified visible Markdown notes."""
    return _safe(get_recent_notes, VAULT_ROOT, max_results)


@mcp.tool()
def ingestion_status() -> dict[str, object]:
    """Show capture counts and whether the acquisition and triage policy is available."""
    return _safe(get_ingestion_status, VAULT_ROOT, STATE_ROOT)


@mcp.tool()
def read_ingestion_policy() -> dict[str, object]:
    """Read the user-authored rules for acquisition, triage, and capture states."""
    return _safe(read_ingestion_policy_from_vault, VAULT_ROOT)


@mcp.tool()
def read_organization_policy() -> dict[str, object]:
    """Read the user-authored rules for conversation and note organization."""
    return _safe(read_organization_policy_from_vault, VAULT_ROOT)


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
        capture_material_in_state,
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
def list_captures(
    status: str = "pending", max_results: int = 20
) -> dict[str, object]:
    """List capture metadata without returning the raw content."""
    return _safe(list_captures_in_state, STATE_ROOT, status, max_results)


@mcp.tool()
def read_capture(capture_id: str) -> dict[str, object]:
    """Read one preserved capture and return its record_sha256 revision token."""
    return _safe(read_capture_from_state, STATE_ROOT, capture_id)


@mcp.tool()
def read_pending_captures(max_results: int = 10) -> dict[str, object]:
    """Read up to 20 pending captures for bounded batch triage without changing them."""
    return _safe(read_pending_captures_from_state, STATE_ROOT, max_results)


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
        update_capture_status_in_state,
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
    return _safe(create_note_in_vault, VAULT_ROOT, STATE_ROOT, path, content)


@mcp.tool()
def create_inbox_note(title: str, content: str) -> dict[str, object]:
    """Create a timestamped note in the dedicated AI Inbox folder."""
    return _safe(create_inbox_note_in_vault, VAULT_ROOT, STATE_ROOT, title, content)


@mcp.tool()
def append_to_note(path: str, content: str, expected_sha256: str) -> dict[str, object]:
    """Append text after verifying the sha256 returned by a fresh read_note call."""
    return _safe(
        append_to_note_in_vault,
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
        update_note_in_vault,
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
        restore_note_version,
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
        move_note_in_vault,
        VAULT_ROOT,
        STATE_ROOT,
        source_path,
        destination_path,
        expected_sha256,
    )


@mcp.tool()
def recent_activity(max_results: int = 20) -> dict[str, object]:
    """Return recent mutation audit metadata without note contents."""
    return _safe(get_recent_activity, STATE_ROOT, max_results)


if __name__ == "__main__":
    mcp.run(transport=RUNTIME_CONFIG.transport)
