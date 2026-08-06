from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows-only test fallback
    fcntl = None


MAX_NOTE_BYTES = 1_000_000
MAX_APPEND_BYTES = 100_000
MAX_CAPTURE_BYTES = 500_000
MAX_TRIAGE_BATCH_RESULTS = 20
MAX_TRIAGE_BATCH_BYTES = 250_000
MAX_QUERY_CHARS = 200
MAX_RESULTS_LIMIT = 100
DEFAULT_RESULTS_LIMIT = 20
MAX_LIST_LIMIT = 500
CONTEXT_CHARS = 120
INBOX_FOLDER = "AI Inbox"
ORGANIZATION_POLICY_NOTE_PATH = "Sistema — Gestione automatica delle note.md"
INGESTION_POLICY_NOTE_PATH = "Sistema — Acquisizione e triage.md"

CAPTURE_STATUSES = {"pending", "ready", "processed", "skipped"}
CAPTURE_SOURCE_KINDS = {"manual", "google-keep", "file", "web", "other"}
CAPTURE_STATUS_TRANSITIONS = {
    "pending": {"ready", "skipped"},
    "ready": {"processed", "skipped"},
    "skipped": {"pending", "ready"},
    "processed": set(),
}

_TASK_PATTERN = re.compile(r"^\s*[-*]\s+\[ \]\s+(.+?)\s*$")
_VERSION_ID_PATTERN = re.compile(r"^\d{8}T\d{6}\.\d{6}Z$")
_CAPTURE_ID_PATTERN = re.compile(r"^cap-[0-9a-f]{32}$")
_WRITE_LOCK = threading.RLock()


class JarvisError(ValueError):
    """Raised when a Jarvis Core operation is invalid or unsafe."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_text(value: datetime | None = None) -> str:
    return (value or _utc_now()).isoformat().replace("+00:00", "Z")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get_vault_root() -> Path:
    root = Path(os.environ.get("VAULT_ROOT", "/vault")).resolve(strict=True)
    if not root.is_dir():
        raise JarvisError("The configured vault root is not a directory.")
    return root


def get_state_root() -> Path:
    root = Path(os.environ.get("STATE_ROOT", "/state")).resolve(strict=True)
    if not root.is_dir():
        raise JarvisError("The configured state root is not a directory.")
    return root


def _validate_relative_parts(value: str, *, markdown: bool) -> tuple[str, ...]:
    if not isinstance(value, str) or not value.strip():
        kind = "note path" if markdown else "path"
        raise JarvisError(f"A non-empty relative {kind} is required.")

    cleaned = value.strip()
    if "\\" in cleaned:
        raise JarvisError("Use forward slashes in vault-relative paths.")

    requested = PurePosixPath(cleaned)
    if requested.is_absolute():
        raise JarvisError("Only paths relative to the vault are allowed.")

    parts = requested.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise JarvisError("The path contains an unsafe component.")
    if any(part.startswith(".") for part in parts):
        raise JarvisError("Hidden files and folders are not accessible.")
    if markdown and not parts[-1].lower().endswith(".md"):
        raise JarvisError("Only Markdown (.md) notes are supported.")
    return parts


def _ensure_inside(root: Path, path: Path, *, strict: bool) -> Path:
    try:
        resolved = path.resolve(strict=strict)
        resolved.relative_to(root)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise JarvisError("The path does not resolve safely inside the vault.") from exc
    return resolved


def _reject_symlink_ancestors(root: Path, parts: tuple[str, ...]) -> None:
    current = root
    for part in parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise JarvisError("Symbolic links are not accessible.")


def _existing_note(root: Path, relative_path: str) -> Path:
    parts = _validate_relative_parts(relative_path, markdown=True)
    _reject_symlink_ancestors(root, parts)
    note = _ensure_inside(root, root.joinpath(*parts), strict=True)
    if not note.is_file():
        raise JarvisError("The requested note is not a file.")
    return note


def _new_note_target(root: Path, relative_path: str) -> Path:
    parts = _validate_relative_parts(relative_path, markdown=True)
    _reject_symlink_ancestors(root, parts)
    target = _ensure_inside(root, root.joinpath(*parts), strict=False)
    return target


def _folder(root: Path, relative_folder: str = "") -> Path:
    if not relative_folder.strip():
        return root
    parts = _validate_relative_parts(relative_folder, markdown=False)
    _reject_symlink_ancestors(root, parts)
    folder = _ensure_inside(root, root.joinpath(*parts), strict=True)
    if not folder.is_dir():
        raise JarvisError("The requested folder is not a directory.")
    return folder


def _read_note_bytes(note: Path) -> bytes:
    size = note.stat().st_size
    if size > MAX_NOTE_BYTES:
        raise JarvisError("The note is too large to process safely.")
    try:
        return note.read_bytes()
    except OSError as exc:
        raise JarvisError("The note could not be read.") from exc


def _decode_note(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeError as exc:
        raise JarvisError("The note is not valid UTF-8 text.") from exc


def _encode_content(content: str, *, append: bool = False) -> bytes:
    if not isinstance(content, str):
        raise JarvisError("Note content must be text.")
    data = content.encode("utf-8")
    limit = MAX_APPEND_BYTES if append else MAX_NOTE_BYTES
    if len(data) > limit:
        kind = "append" if append else "note"
        raise JarvisError(f"The {kind} content exceeds the safety limit.")
    return data


def _validate_limit(value: int, *, maximum: int = MAX_RESULTS_LIMIT) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise JarvisError("The result limit must be an integer.")
    if not 1 <= value <= maximum:
        raise JarvisError(f"The result limit must be between 1 and {maximum}.")
    return value


def _markdown_files(root: Path, start: Path | None = None) -> Iterator[Path]:
    search_root = start or root
    for current, directories, files in os.walk(search_root, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            name
            for name in directories
            if not name.startswith(".") and not (current_path / name).is_symlink()
        )
        for name in sorted(files):
            if name.startswith(".") or not name.lower().endswith(".md"):
                continue
            path = current_path / name
            if path.is_symlink():
                continue
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
            except (FileNotFoundError, RuntimeError, ValueError):
                continue
            if resolved.is_file():
                yield resolved


def _note_metadata(root: Path, note: Path, *, include_hash: bool) -> dict[str, object]:
    stat = note.stat()
    result: dict[str, object] = {
        "path": note.relative_to(root).as_posix(),
        "size_bytes": stat.st_size,
        "modified_utc": _utc_text(datetime.fromtimestamp(stat.st_mtime, timezone.utc)),
    }
    if include_hash:
        result["sha256"] = _sha256_bytes(_read_note_bytes(note))
    return result


def read_note_from_vault(root: Path, relative_path: str) -> dict[str, object]:
    note = _existing_note(root, relative_path)
    data = _read_note_bytes(note)
    result = _note_metadata(root, note, include_hash=False)
    result.update({"sha256": _sha256_bytes(data), "content": _decode_note(data)})
    return result


def list_notes_in_vault(
    root: Path,
    relative_folder: str = "",
    max_results: int = 100,
    *,
    offset: int = 0,
    filename: str | None = None,
) -> dict[str, object]:
    limit = _validate_limit(max_results, maximum=MAX_LIST_LIMIT)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise JarvisError("The result offset must be a non-negative integer.")
    if filename is not None and (
        not isinstance(filename, str)
        or not filename
        or "/" in filename
        or "\\" in filename
    ):
        raise JarvisError("The filename filter must be one plain filename.")
    start = _folder(root, relative_folder)
    notes: list[dict[str, object]] = []
    limit_reached = False
    matched = 0
    for note in _markdown_files(root, start):
        if filename is not None and note.name != filename:
            continue
        if matched < offset:
            matched += 1
            continue
        if len(notes) >= limit:
            limit_reached = True
            break
        notes.append(_note_metadata(root, note, include_hash=False))
        matched += 1
    return {
        "folder": start.relative_to(root).as_posix() if start != root else "",
        "notes": notes,
        "limit_reached": limit_reached,
        "offset": offset,
    }


def search_vault(
    root: Path, query: str, max_results: int = DEFAULT_RESULTS_LIMIT
) -> dict[str, object]:
    if not isinstance(query, str):
        raise JarvisError("The search query must be text.")
    cleaned_query = query.strip()
    if len(cleaned_query) < 2:
        raise JarvisError("The search query must contain at least two characters.")
    if len(cleaned_query) > MAX_QUERY_CHARS:
        raise JarvisError(f"The search query cannot exceed {MAX_QUERY_CHARS} characters.")
    limit = _validate_limit(max_results)

    needle = cleaned_query.casefold()
    matches: list[dict[str, object]] = []
    skipped_large_files = 0
    for note in _markdown_files(root):
        try:
            if note.stat().st_size > MAX_NOTE_BYTES:
                skipped_large_files += 1
                continue
            text = note.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue

        for line_number, line in enumerate(text.splitlines(), start=1):
            start = line.casefold().find(needle)
            if start == -1:
                continue
            excerpt_start = max(0, start - CONTEXT_CHARS)
            excerpt_end = min(len(line), start + len(cleaned_query) + CONTEXT_CHARS)
            matches.append(
                {
                    "path": note.relative_to(root).as_posix(),
                    "line": line_number,
                    "excerpt": line[excerpt_start:excerpt_end].strip(),
                }
            )
            if len(matches) >= limit:
                return {
                    "query": cleaned_query,
                    "matches": matches,
                    "limit_reached": True,
                    "skipped_large_files": skipped_large_files,
                }
    return {
        "query": cleaned_query,
        "matches": matches,
        "limit_reached": False,
        "skipped_large_files": skipped_large_files,
    }


def list_tasks_in_vault(root: Path, max_results: int = 100) -> dict[str, object]:
    limit = _validate_limit(max_results, maximum=MAX_LIST_LIMIT)
    tasks: list[dict[str, object]] = []
    skipped_large_files = 0
    for note in _markdown_files(root):
        try:
            if note.stat().st_size > MAX_NOTE_BYTES:
                skipped_large_files += 1
                continue
            text = note.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            match = _TASK_PATTERN.match(line)
            if not match:
                continue
            tasks.append(
                {
                    "path": note.relative_to(root).as_posix(),
                    "line": line_number,
                    "task": match.group(1),
                }
            )
            if len(tasks) >= limit:
                return {
                    "tasks": tasks,
                    "limit_reached": True,
                    "skipped_large_files": skipped_large_files,
                }
    return {
        "tasks": tasks,
        "limit_reached": False,
        "skipped_large_files": skipped_large_files,
    }


def recent_notes(root: Path, max_results: int = 20) -> dict[str, object]:
    limit = _validate_limit(max_results, maximum=MAX_LIST_LIMIT)
    notes = sorted(_markdown_files(root), key=lambda path: path.stat().st_mtime, reverse=True)
    return {
        "notes": [_note_metadata(root, note, include_hash=False) for note in notes[:limit]],
        "limit_reached": len(notes) > limit,
    }


@contextmanager
def _mutation_lock(state: Path) -> Iterator[None]:
    """Serialize mutations inside one process and across MCP containers."""
    with _WRITE_LOCK:
        if fcntl is None:
            yield
            return

        lock_path = state / ".jarvis-mutation.lock"
        with lock_path.open("a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _verify_expected_hash(data: bytes, expected_sha256: str) -> str:
    if not isinstance(expected_sha256, str) or not re.fullmatch(
        r"[0-9a-fA-F]{64}", expected_sha256.strip()
    ):
        raise JarvisError("A valid expected_sha256 from read_note is required.")
    actual = _sha256_bytes(data)
    if actual != expected_sha256.strip().lower():
        raise JarvisError(
            "The note changed since it was read. Read it again before modifying it."
        )
    return actual


def _verify_version_hash(data: bytes, expected_sha256: str) -> str:
    if not isinstance(expected_sha256, str) or not re.fullmatch(
        r"[0-9a-fA-F]{64}", expected_sha256.strip()
    ):
        raise JarvisError(
            "A valid expected_version_sha256 from read_version is required."
        )
    actual = _sha256_bytes(data)
    if actual != expected_sha256.strip().lower():
        raise JarvisError(
            "The saved version does not match the expected hash. Read it again before "
            "restoring it."
        )
    return actual


def _validate_version_id(value: str) -> str:
    if not isinstance(value, str):
        raise JarvisError("A valid version_id is required.")
    cleaned = value.strip()
    if not _VERSION_ID_PATTERN.fullmatch(cleaned):
        raise JarvisError("A valid version_id returned by list_versions is required.")
    return cleaned


def _saved_version(state: Path, relative_path: str, version_id: str) -> Path:
    parts = _validate_relative_parts(relative_path, markdown=True)
    cleaned_version = _validate_version_id(version_id)
    state_parts = ("versions", cleaned_version, *parts)
    _reject_symlink_ancestors(state, state_parts)
    snapshot = _ensure_inside(state, state.joinpath(*state_parts), strict=True)
    if not snapshot.is_file():
        raise JarvisError("The requested saved version is not a file.")
    return snapshot


def _snapshot_note(state: Path, root: Path, note: Path, data: bytes) -> str:
    stamp = _utc_now().strftime("%Y%m%dT%H%M%S.%fZ")
    relative = note.relative_to(root)
    snapshot = state / "versions" / stamp / relative
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    with snapshot.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return snapshot.relative_to(state).as_posix()


def list_note_versions(
    state: Path, relative_path: str, max_results: int = DEFAULT_RESULTS_LIMIT
) -> dict[str, object]:
    parts = _validate_relative_parts(relative_path, markdown=True)
    normalized_path = PurePosixPath(*parts).as_posix()
    limit = _validate_limit(max_results)
    versions_root = state / "versions"
    if not versions_root.exists():
        return {"path": normalized_path, "versions": [], "limit_reached": False}
    if versions_root.is_symlink() or not versions_root.is_dir():
        raise JarvisError("The versions store is not a safe directory.")

    results: list[dict[str, object]] = []
    limit_reached = False
    for version_dir in sorted(versions_root.iterdir(), reverse=True):
        if (
            version_dir.is_symlink()
            or not version_dir.is_dir()
            or not _VERSION_ID_PATTERN.fullmatch(version_dir.name)
        ):
            continue
        candidate = version_dir.joinpath(*parts)
        if not candidate.exists() or candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            _reject_symlink_ancestors(
                state, ("versions", version_dir.name, *parts)
            )
            snapshot = _ensure_inside(state, candidate, strict=True)
            data = _read_note_bytes(snapshot)
        except JarvisError:
            continue
        if len(results) >= limit:
            limit_reached = True
            break
        results.append(
            {
                "version_id": version_dir.name,
                "path": normalized_path,
                "sha256": _sha256_bytes(data),
                "size_bytes": len(data),
            }
        )
    return {
        "path": normalized_path,
        "versions": results,
        "limit_reached": limit_reached,
    }


def read_note_version(
    state: Path, relative_path: str, version_id: str
) -> dict[str, object]:
    snapshot = _saved_version(state, relative_path, version_id)
    data = _read_note_bytes(snapshot)
    return {
        "version_id": _validate_version_id(version_id),
        "path": PurePosixPath(*_validate_relative_parts(relative_path, markdown=True)).as_posix(),
        "sha256": _sha256_bytes(data),
        "size_bytes": len(data),
        "content": _decode_note(data),
    }


def _append_audit(state: Path, record: dict[str, object]) -> str:
    event_id = uuid.uuid4().hex
    event = {"event_id": event_id, "timestamp_utc": _utc_text(), **record}
    audit_file = state / "audit.jsonl"
    with audit_file.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return event_id


def _atomic_replace(note: Path, data: bytes, *, mode: int | None = None) -> None:
    note.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=note.parent, prefix=".jarvis-", suffix=".tmp", delete=False
        ) as handle:
            temp_name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temp_name, mode & 0o777)
        os.replace(temp_name, note)
        temp_name = None
    finally:
        if temp_name is not None:
            try:
                Path(temp_name).unlink()
            except FileNotFoundError:
                pass


def create_note_in_vault(
    root: Path, state: Path, relative_path: str, content: str
) -> dict[str, object]:
    data = _encode_content(content)
    target = _new_note_target(root, relative_path)
    with _mutation_lock(state):
        if target.exists():
            raise JarvisError("The target note already exists; it will not be overwritten.")
        target.parent.mkdir(parents=True, exist_ok=True)
        _reject_symlink_ancestors(root, target.relative_to(root).parts)
        with target.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        after_hash = _sha256_bytes(data)
        event_id = _append_audit(
            state,
            {
                "action": "create_note",
                "path": target.relative_to(root).as_posix(),
                "before_sha256": None,
                "after_sha256": after_hash,
                "size_bytes": len(data),
                "backup_path": None,
            },
        )
    return {
        "created": True,
        "path": target.relative_to(root).as_posix(),
        "sha256": after_hash,
        "size_bytes": len(data),
        "audit_event_id": event_id,
    }


def _replace_existing_note(
    *,
    action: str,
    root: Path,
    state: Path,
    relative_path: str,
    new_data: bytes,
    expected_sha256: str,
) -> dict[str, object]:
    note = _existing_note(root, relative_path)
    with _mutation_lock(state):
        current_data = _read_note_bytes(note)
        before_hash = _verify_expected_hash(current_data, expected_sha256)
        original_mode = note.stat().st_mode
        if len(new_data) > MAX_NOTE_BYTES:
            raise JarvisError("The resulting note exceeds the safety limit.")
        backup_path = _snapshot_note(state, root, note, current_data)
        # Syncthing is external and does not share our in-process lock. Check
        # once more immediately before replacing to avoid a silent overwrite.
        latest_data = _read_note_bytes(note)
        if _sha256_bytes(latest_data) != before_hash:
            raise JarvisError(
                "The note changed during the operation. Read it again before modifying it."
            )
        _atomic_replace(note, new_data, mode=original_mode)
        after_hash = _sha256_bytes(new_data)
        event_id = _append_audit(
            state,
            {
                "action": action,
                "path": note.relative_to(root).as_posix(),
                "before_sha256": before_hash,
                "after_sha256": after_hash,
                "size_bytes": len(new_data),
                "backup_path": backup_path,
            },
        )
    return {
        "updated": True,
        "path": note.relative_to(root).as_posix(),
        "before_sha256": before_hash,
        "sha256": after_hash,
        "size_bytes": len(new_data),
        "backup_path": backup_path,
        "audit_event_id": event_id,
    }


def update_note_in_vault(
    root: Path,
    state: Path,
    relative_path: str,
    content: str,
    expected_sha256: str,
) -> dict[str, object]:
    return _replace_existing_note(
        action="update_note",
        root=root,
        state=state,
        relative_path=relative_path,
        new_data=_encode_content(content),
        expected_sha256=expected_sha256,
    )


def append_to_note_in_vault(
    root: Path,
    state: Path,
    relative_path: str,
    content: str,
    expected_sha256: str,
) -> dict[str, object]:
    append_data = _encode_content(content, append=True)
    note = _existing_note(root, relative_path)
    current_data = _read_note_bytes(note)
    return _replace_existing_note(
        action="append_to_note",
        root=root,
        state=state,
        relative_path=relative_path,
        new_data=current_data + append_data,
        expected_sha256=expected_sha256,
    )


def restore_note_version(
    root: Path,
    state: Path,
    relative_path: str,
    version_id: str,
    expected_sha256: str,
    expected_version_sha256: str,
) -> dict[str, object]:
    note = _existing_note(root, relative_path)
    saved_version = _saved_version(state, relative_path, version_id)
    version_data = _read_note_bytes(saved_version)
    version_hash = _verify_version_hash(version_data, expected_version_sha256)

    with _mutation_lock(state):
        current_data = _read_note_bytes(note)
        before_hash = _verify_expected_hash(current_data, expected_sha256)
        original_mode = note.stat().st_mode
        backup_path = _snapshot_note(state, root, note, current_data)

        latest_data = _read_note_bytes(note)
        if _sha256_bytes(latest_data) != before_hash:
            raise JarvisError(
                "The note changed during the operation. Read it again before restoring it."
            )

        latest_version_data = _read_note_bytes(saved_version)
        if _sha256_bytes(latest_version_data) != version_hash:
            raise JarvisError(
                "The saved version changed during the operation. Read it again before "
                "restoring it."
            )

        _atomic_replace(note, latest_version_data, mode=original_mode)
        after_hash = _sha256_bytes(latest_version_data)
        event_id = _append_audit(
            state,
            {
                "action": "restore_version",
                "path": note.relative_to(root).as_posix(),
                "before_sha256": before_hash,
                "after_sha256": after_hash,
                "size_bytes": len(latest_version_data),
                "backup_path": backup_path,
                "restored_version_id": _validate_version_id(version_id),
                "restored_version_sha256": version_hash,
            },
        )

    return {
        "restored": True,
        "path": note.relative_to(root).as_posix(),
        "version_id": _validate_version_id(version_id),
        "before_sha256": before_hash,
        "sha256": after_hash,
        "size_bytes": len(latest_version_data),
        "backup_path": backup_path,
        "audit_event_id": event_id,
    }


def move_note_in_vault(
    root: Path,
    state: Path,
    source_path: str,
    destination_path: str,
    expected_sha256: str,
) -> dict[str, object]:
    source = _existing_note(root, source_path)
    destination = _new_note_target(root, destination_path)
    if source == destination:
        raise JarvisError("Source and destination must be different.")
    with _mutation_lock(state):
        current_data = _read_note_bytes(source)
        before_hash = _verify_expected_hash(current_data, expected_sha256)
        if destination.exists():
            raise JarvisError("The destination already exists; it will not be overwritten.")
        backup_path = _snapshot_note(state, root, source, current_data)
        latest_data = _read_note_bytes(source)
        if _sha256_bytes(latest_data) != before_hash:
            raise JarvisError(
                "The note changed during the operation. Read it again before moving it."
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        _reject_symlink_ancestors(root, destination.relative_to(root).parts)
        os.replace(source, destination)
        event_id = _append_audit(
            state,
            {
                "action": "move_note",
                "path": source.relative_to(root).as_posix(),
                "destination_path": destination.relative_to(root).as_posix(),
                "before_sha256": before_hash,
                "after_sha256": before_hash,
                "size_bytes": len(current_data),
                "backup_path": backup_path,
            },
        )
    return {
        "moved": True,
        "source_path": source.relative_to(root).as_posix(),
        "destination_path": destination.relative_to(root).as_posix(),
        "sha256": before_hash,
        "backup_path": backup_path,
        "audit_event_id": event_id,
    }


def create_inbox_note(
    root: Path, state: Path, title: str, content: str
) -> dict[str, object]:
    if not isinstance(title, str) or not title.strip():
        raise JarvisError("A non-empty title is required.")
    cleaned = re.sub(r"[^\w\- ]+", "", title.strip(), flags=re.UNICODE)
    slug = re.sub(r"[\s_]+", "-", cleaned).strip("-").lower()
    if not slug:
        raise JarvisError("The title does not contain usable filename characters.")
    slug = slug[:80].rstrip("-")
    stamp = _utc_now().strftime("%Y%m%d-%H%M%S")
    path = f"{INBOX_FOLDER}/{stamp}-{slug}.md"
    body = content if content.startswith("# ") else f"# {title.strip()}\n\n{content}"
    return create_note_in_vault(root, state, path, body)


def read_organization_policy(root: Path) -> dict[str, object]:
    """Read the canonical, user-editable note organization policy."""
    result = read_note_from_vault(root, ORGANIZATION_POLICY_NOTE_PATH)
    result["policy_path"] = result.pop("path")
    return result


def read_ingestion_policy(root: Path) -> dict[str, object]:
    """Read the canonical, user-editable acquisition and triage policy."""
    result = read_note_from_vault(root, INGESTION_POLICY_NOTE_PATH)
    result["policy_path"] = result.pop("path")
    return result


def _validate_capture_id(value: str) -> str:
    if not isinstance(value, str):
        raise JarvisError("A valid capture_id is required.")
    cleaned = value.strip().lower()
    if not _CAPTURE_ID_PATTERN.fullmatch(cleaned):
        raise JarvisError("A valid capture_id returned by Jarvis is required.")
    return cleaned


def _captures_root(state: Path, *, create: bool) -> Path:
    captures = state / "captures"
    if captures.exists():
        if captures.is_symlink() or not captures.is_dir():
            raise JarvisError("The capture store is not a safe directory.")
    elif create:
        captures.mkdir(mode=0o700)
    return captures


def _capture_path(state: Path, capture_id: str, *, strict: bool) -> Path:
    cleaned = _validate_capture_id(capture_id)
    captures = _captures_root(state, create=not strict)
    path = captures / f"{cleaned}.json"
    if path.is_symlink():
        raise JarvisError("Symbolic links are not accessible.")
    if strict and (not path.exists() or not path.is_file()):
        raise JarvisError("The requested capture does not exist.")
    return _ensure_inside(state, path, strict=strict)


def _encode_capture_record(record: dict[str, object]) -> bytes:
    return (
        json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _read_capture_record(
    state: Path, capture_id: str
) -> tuple[Path, bytes, dict[str, object]]:
    path = _capture_path(state, capture_id, strict=True)
    data = path.read_bytes()
    if len(data) > MAX_CAPTURE_BYTES + 100_000:
        raise JarvisError("The stored capture is too large to process safely.")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise JarvisError("The stored capture is not valid UTF-8 JSON.") from exc
    if not isinstance(value, dict) or value.get("capture_id") != capture_id:
        raise JarvisError("The stored capture record is invalid.")
    return path, data, value


def _validate_capture_text(value: str, name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise JarvisError(f"Capture {name} must be text.")
    cleaned = value.strip()
    if not cleaned:
        raise JarvisError(f"Capture {name} cannot be empty.")
    if len(cleaned) > maximum:
        raise JarvisError(f"Capture {name} cannot exceed {maximum} characters.")
    return cleaned


def _validate_capture_labels(labels: list[str] | None) -> list[str]:
    if labels is None:
        return []
    if not isinstance(labels, list) or len(labels) > 20:
        raise JarvisError("Capture labels must be a list containing at most 20 items.")
    cleaned: list[str] = []
    for label in labels:
        item = _validate_capture_text(label, "label", 80)
        if item not in cleaned:
            cleaned.append(item)
    return cleaned


def _capture_metadata(data: bytes, record: dict[str, object]) -> dict[str, object]:
    return {
        "capture_id": record["capture_id"],
        "title": record["title"],
        "source_kind": record["source_kind"],
        "source_ref": record["source_ref"],
        "source_created_utc": record.get("source_created_utc", ""),
        "source_updated_utc": record.get("source_updated_utc", ""),
        "labels": record["labels"],
        "status": record["status"],
        "created_utc": record["created_utc"],
        "status_updated_utc": record["status_updated_utc"],
        "content_sha256": record["content_sha256"],
        "content_size_bytes": record["content_size_bytes"],
        "output_paths": record["output_paths"],
        "summary": record["summary"],
        "record_sha256": _sha256_bytes(data),
    }


def capture_material(
    state: Path,
    title: str,
    content: str,
    source_kind: str = "manual",
    source_ref: str = "",
    labels: list[str] | None = None,
    source_created_utc: str = "",
    source_updated_utc: str = "",
) -> dict[str, object]:
    cleaned_title = _validate_capture_text(title, "title", 200)
    if not isinstance(content, str) or not content.strip():
        raise JarvisError("Capture content must be non-empty text.")
    content_data = content.encode("utf-8")
    if len(content_data) > MAX_CAPTURE_BYTES:
        raise JarvisError(
            f"Capture content cannot exceed {MAX_CAPTURE_BYTES} UTF-8 bytes."
        )
    if not isinstance(source_kind, str) or source_kind not in CAPTURE_SOURCE_KINDS:
        allowed = ", ".join(sorted(CAPTURE_SOURCE_KINDS))
        raise JarvisError(f"source_kind must be one of: {allowed}.")
    if not isinstance(source_ref, str) or len(source_ref.strip()) > 500:
        raise JarvisError("source_ref must be text containing at most 500 characters.")
    cleaned_labels = _validate_capture_labels(labels)
    source_created = _validate_optional_utc_timestamp(
        source_created_utc, "source_created_utc"
    )
    source_updated = _validate_optional_utc_timestamp(
        source_updated_utc, "source_updated_utc"
    )
    content_hash = _sha256_bytes(content_data)

    with _mutation_lock(state):
        captures = _captures_root(state, create=True)
        for candidate in sorted(captures.glob("cap-*.json")):
            if candidate.is_symlink() or not candidate.is_file():
                continue
            try:
                candidate_data = candidate.read_bytes()
                candidate_record = json.loads(candidate_data.decode("utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if (
                isinstance(candidate_record, dict)
                and candidate_record.get("content_sha256") == content_hash
                and candidate_record.get("source_kind") == source_kind
                and candidate_record.get("source_ref") == source_ref.strip()
            ):
                result = _capture_metadata(candidate_data, candidate_record)
                result.update({"created": False, "duplicate": True})
                return result

        capture_id = f"cap-{uuid.uuid4().hex}"
        now = _utc_text()
        record: dict[str, object] = {
            "schema_version": 1,
            "capture_id": capture_id,
            "title": cleaned_title,
            "content": content,
            "content_sha256": content_hash,
            "content_size_bytes": len(content_data),
            "source_kind": source_kind,
            "source_ref": source_ref.strip(),
            "source_created_utc": source_created,
            "source_updated_utc": source_updated,
            "labels": cleaned_labels,
            "status": "pending",
            "created_utc": now,
            "status_updated_utc": now,
            "output_paths": [],
            "summary": "",
        }
        data = _encode_capture_record(record)
        path = _capture_path(state, capture_id, strict=False)
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        event_id = _append_audit(
            state,
            {
                "action": "capture_material",
                "capture_id": capture_id,
                "content_sha256": content_hash,
                "content_size_bytes": len(content_data),
                "source_kind": source_kind,
            },
        )
    result = _capture_metadata(data, record)
    result.update(
        {"created": True, "duplicate": False, "audit_event_id": event_id}
    )
    return result


def _validate_optional_utc_timestamp(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise JarvisError(f"{name} must be text.")
    cleaned = value.strip()
    if not cleaned:
        return ""
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError as exc:
        raise JarvisError(f"{name} must be a valid ISO 8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise JarvisError(f"{name} must include a timezone.")
    return _utc_text(parsed.astimezone(timezone.utc))


def list_captures(
    state: Path, status: str = "pending", max_results: int = DEFAULT_RESULTS_LIMIT
) -> dict[str, object]:
    if not isinstance(status, str) or status not in CAPTURE_STATUSES | {"all"}:
        allowed = ", ".join(sorted(CAPTURE_STATUSES | {"all"}))
        raise JarvisError(f"status must be one of: {allowed}.")
    limit = _validate_limit(max_results, maximum=MAX_LIST_LIMIT)
    captures = _captures_root(state, create=False)
    if not captures.exists():
        return {"status": status, "captures": [], "limit_reached": False}
    available: list[dict[str, object]] = []
    for candidate in captures.glob("cap-*.json"):
        if candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            data = candidate.read_bytes()
            record = json.loads(data.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict) or (
            status != "all" and record.get("status") != status
        ):
            continue
        try:
            available.append(_capture_metadata(data, record))
        except KeyError:
            continue
    available.sort(key=lambda item: str(item["created_utc"]), reverse=True)
    return {
        "status": status,
        "captures": available[:limit],
        "limit_reached": len(available) > limit,
    }


def read_capture(state: Path, capture_id: str) -> dict[str, object]:
    _, data, record = _read_capture_record(state, _validate_capture_id(capture_id))
    result = _capture_metadata(data, record)
    result["content"] = record["content"]
    return result


def read_pending_captures(
    state: Path, max_results: int = 10
) -> dict[str, object]:
    """Read a bounded batch of pending captures without changing their status."""
    limit = _validate_limit(max_results, maximum=MAX_TRIAGE_BATCH_RESULTS)
    listed = list_captures(state, "pending", limit)
    results: list[dict[str, object]] = []
    total_content_bytes = 0
    stopped_for_size = False

    for metadata in listed["captures"]:
        _, data, record = _read_capture_record(state, str(metadata["capture_id"]))
        content = record["content"]
        if not isinstance(content, str):
            raise JarvisError("The stored capture content is invalid.")
        content_bytes = len(content.encode("utf-8"))
        if results and total_content_bytes + content_bytes > MAX_TRIAGE_BATCH_BYTES:
            stopped_for_size = True
            break
        item = _capture_metadata(data, record)
        item["content"] = content
        results.append(item)
        total_content_bytes += content_bytes

    return {
        "status": "pending",
        "captures": results,
        "capture_count": len(results),
        "content_bytes": total_content_bytes,
        "limit_reached": bool(listed["limit_reached"] or stopped_for_size),
    }


def update_capture_status(
    root: Path,
    state: Path,
    capture_id: str,
    status: str,
    expected_record_sha256: str,
    output_paths: list[str] | None = None,
    summary: str = "",
) -> dict[str, object]:
    cleaned_id = _validate_capture_id(capture_id)
    if not isinstance(status, str) or status not in CAPTURE_STATUSES:
        allowed = ", ".join(sorted(CAPTURE_STATUSES))
        raise JarvisError(f"status must be one of: {allowed}.")
    if (
        not isinstance(summary, str)
        or not summary.strip()
        or len(summary) > 2_000
    ):
        raise JarvisError(
            "summary must be non-empty text containing at most 2000 characters."
        )
    if output_paths is None:
        output_paths = []
    if not isinstance(output_paths, list) or len(output_paths) > 20:
        raise JarvisError("output_paths must contain at most 20 note paths.")
    normalized_paths: list[str] = []
    for value in output_paths:
        note = _existing_note(root, value)
        relative = note.relative_to(root).as_posix()
        if relative not in normalized_paths:
            normalized_paths.append(relative)
    if status == "processed" and not normalized_paths:
        raise JarvisError("A processed capture must reference at least one output note.")
    if status != "processed" and normalized_paths:
        raise JarvisError("Only processed captures can reference output notes.")
    if not isinstance(expected_record_sha256, str) or not re.fullmatch(
        r"[0-9a-fA-F]{64}", expected_record_sha256.strip()
    ):
        raise JarvisError("A valid record_sha256 from read_capture is required.")

    with _mutation_lock(state):
        path, current_data, record = _read_capture_record(state, cleaned_id)
        current_hash = _sha256_bytes(current_data)
        if current_hash != expected_record_sha256.strip().lower():
            raise JarvisError(
                "The capture changed since it was read. Read it again before updating it."
            )
        before_status = record["status"]
        allowed_transitions = CAPTURE_STATUS_TRANSITIONS.get(before_status, set())
        if status not in allowed_transitions:
            raise JarvisError(
                f"The capture status transition {before_status} -> {status} is not allowed."
            )
        record["status"] = status
        record["status_updated_utc"] = _utc_text()
        record["output_paths"] = normalized_paths
        record["summary"] = summary.strip()
        new_data = _encode_capture_record(record)
        _atomic_replace(path, new_data, mode=path.stat().st_mode)
        event_id = _append_audit(
            state,
            {
                "action": "update_capture_status",
                "capture_id": cleaned_id,
                "before_status": before_status,
                "status": status,
                "output_paths": normalized_paths,
            },
        )
    result = _capture_metadata(new_data, record)
    result.update({"updated": True, "audit_event_id": event_id})
    return result


def ingestion_status(root: Path, state: Path) -> dict[str, object]:
    counts = {status: 0 for status in sorted(CAPTURE_STATUSES)}
    captures = _captures_root(state, create=False)
    if captures.exists():
        for candidate in captures.glob("cap-*.json"):
            if candidate.is_symlink() or not candidate.is_file():
                continue
            try:
                record = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            status = record.get("status") if isinstance(record, dict) else None
            if status in counts:
                counts[status] += 1
    try:
        policy = read_ingestion_policy(root)
        policy_result: dict[str, object] = {
            "available": True,
            "path": policy["policy_path"],
            "sha256": policy["sha256"],
        }
    except JarvisError:
        policy_result = {
            "available": False,
            "path": INGESTION_POLICY_NOTE_PATH,
            "sha256": None,
        }
    return {
        "captures": {"total": sum(counts.values()), **counts},
        "policy": policy_result,
        "raw_material_is_preserved": True,
        "automatic_deletion_available": False,
    }


def recent_activity(state: Path, max_results: int = 20) -> dict[str, object]:
    limit = _validate_limit(max_results, maximum=100)
    audit_file = state / "audit.jsonl"
    if not audit_file.exists():
        return {"events": [], "limit_reached": False}
    events: list[dict[str, object]] = []
    for line in audit_file.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    selected = events[-limit:]
    selected.reverse()
    return {"events": selected, "limit_reached": len(events) > limit}


def vault_status(root: Path, state: Path) -> dict[str, object]:
    notes = list(_markdown_files(root))
    audit_file = state / "audit.jsonl"
    audit_events = 0
    if audit_file.exists():
        with audit_file.open("r", encoding="utf-8") as handle:
            audit_events = sum(1 for line in handle if line.strip())
    return {
        "service": "Jarvis Core",
        "version": "1.4.0",
        "vault_mode": "read-write-with-versioning",
        "session_mode": "multi-session-with-shared-mutation-lock",
        "concurrent_reads_available": True,
        "concurrent_mutations_serialized": True,
        "note_count": len(notes),
        "audit_event_count": audit_events,
        "ingestion_available": True,
        "raw_material_is_preserved": True,
        "capture_status_transition_policy_enforced": True,
        "policy_paths": {
            "organization": ORGANIZATION_POLICY_NOTE_PATH,
            "ingestion": INGESTION_POLICY_NOTE_PATH,
        },
        "delete_tool_available": False,
        "hidden_paths_accessible": False,
        "network_required": False,
    }
