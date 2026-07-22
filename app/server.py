from mcp.server.fastmcp import FastMCP

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


VAULT_ROOT = get_vault_root()
STATE_ROOT = get_state_root()

mcp = FastMCP(
    "Jarvis Core v1.3.3",
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
)


def _safe(callable_, *args, **kwargs) -> dict[str, object]:
    try:
        return callable_(*args, **kwargs)
    except (JarvisError, OSError, UnicodeError) as exc:
        return {"error": str(exc)}


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
    mcp.run(transport="stdio")
