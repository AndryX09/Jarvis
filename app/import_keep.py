from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

try:
    from vault_core import JarvisError, capture_material
except ModuleNotFoundError:  # Package import used by the local test suite.
    from app.vault_core import JarvisError, capture_material


MAX_ARCHIVE_BYTES = 500_000_000
MAX_JSON_BYTES = 1_000_000
KEEP_PREFIX = "Takeout/Keep/"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_entry_name(name: str) -> str:
    cleaned = name.replace("\\", "/")
    path = PurePosixPath(cleaned)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise JarvisError("The Takeout archive contains an unsafe path.")
    if not cleaned.startswith(KEEP_PREFIX):
        raise JarvisError("The Takeout archive contains a JSON file outside Keep.")
    return cleaned


def _timestamp_from_usec(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return ""
    return (
        datetime.fromtimestamp(value / 1_000_000, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _keep_labels(note: dict[str, object]) -> list[str]:
    labels: list[str] = []
    raw_labels = note.get("labels", [])
    if isinstance(raw_labels, list):
        for item in raw_labels:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                value = item["name"].strip()
                if value and value not in labels:
                    labels.append(value[:80])
    if note.get("isPinned") is True:
        labels.append("keep:pinned")
    if note.get("isArchived") is True:
        labels.append("keep:archived")
    color = note.get("color")
    if isinstance(color, str) and color.strip():
        labels.append(f"keep:color:{color.strip().lower()}"[:80])
    return labels[:20]


def _keep_content(note: dict[str, object]) -> tuple[str, int]:
    text = note.get("textContent")
    if isinstance(text, str) and text.strip():
        body = text
    else:
        lines: list[str] = []
        raw_list = note.get("listContent", [])
        if isinstance(raw_list, list):
            for item in raw_list:
                if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                    continue
                marker = "x" if item.get("isChecked") is True else " "
                lines.append(f"- [{marker}] {item['text']}")
        body = "\n".join(lines)

    attachment_lines: list[str] = []
    raw_attachments = note.get("attachments", [])
    if isinstance(raw_attachments, list):
        for item in raw_attachments:
            if not isinstance(item, dict):
                continue
            file_path = item.get("filePath")
            mime = item.get("mimetype")
            if isinstance(file_path, str) and file_path.strip():
                description = file_path.strip()
                if isinstance(mime, str) and mime.strip():
                    description += f" ({mime.strip()})"
                attachment_lines.append(f"- {description}")

    if attachment_lines:
        suffix = "\n\nAllegati originali in Google Takeout:\n" + "\n".join(
            attachment_lines
        )
        body = body + suffix if body else suffix.lstrip()
    if not body.strip():
        body = "[Nota Keep senza contenuto testuale]"
    return body, len(attachment_lines)


def inspect_keep_archive(archive_path: Path) -> dict[str, object]:
    if not archive_path.is_file():
        raise JarvisError("The Takeout archive does not exist.")
    if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise JarvisError("The Takeout archive exceeds the safety limit.")

    archive_hash = _sha256_file(archive_path)
    captures: list[dict[str, object]] = []
    attachment_count = 0
    with zipfile.ZipFile(archive_path, "r") as archive:
        for entry in archive.infolist():
            if entry.is_dir() or not entry.filename.lower().endswith(".json"):
                continue
            name = _safe_entry_name(entry.filename)
            if entry.file_size > MAX_JSON_BYTES:
                raise JarvisError("A Keep JSON note exceeds the safety limit.")
            try:
                raw = archive.read(entry)
                note = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError, OSError) as exc:
                raise JarvisError("A Keep JSON note is invalid.") from exc
            if not isinstance(note, dict):
                raise JarvisError("A Keep JSON note is not an object.")
            title = note.get("title")
            if not isinstance(title, str) or not title.strip():
                created = _timestamp_from_usec(note.get("createdTimestampUsec"))
                title = f"Nota Keep {created[:10] or 'senza data'}"
            content, attachments = _keep_content(note)
            attachment_count += attachments
            captures.append(
                {
                    "title": title,
                    "content": content,
                    "source_kind": "google-keep",
                    "source_ref": f"{archive_hash}:{name}",
                    "labels": _keep_labels(note),
                    "source_created_utc": _timestamp_from_usec(
                        note.get("createdTimestampUsec")
                    ),
                    "source_updated_utc": _timestamp_from_usec(
                        note.get("userEditedTimestampUsec")
                    ),
                }
            )
    if not captures:
        raise JarvisError("No Google Keep JSON notes were found in the archive.")
    return {
        "archive_sha256": archive_hash,
        "archive_size_bytes": archive_path.stat().st_size,
        "notes": captures,
        "attachment_references": attachment_count,
    }


def _preserve_archive(archive_path: Path, state: Path, archive_hash: str) -> Path:
    imports = state / "imports" / "google-keep"
    if imports.exists() and (imports.is_symlink() or not imports.is_dir()):
        raise JarvisError("The Google Keep import store is not a safe directory.")
    imports.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = imports / f"{archive_hash}.zip"
    if target.exists():
        if target.is_symlink() or not target.is_file():
            raise JarvisError("The preserved Takeout archive path is unsafe.")
        if _sha256_file(target) != archive_hash:
            raise JarvisError("The preserved Takeout archive failed verification.")
        return target

    temp = imports / f".{archive_hash}.{os.getpid()}.tmp"
    try:
        with archive_path.open("rb") as source, temp.open("xb") as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
            destination.flush()
            os.fsync(destination.fileno())
        if _sha256_file(temp) != archive_hash:
            raise JarvisError("The copied Takeout archive failed verification.")
        os.replace(temp, target)
    finally:
        if temp.exists():
            temp.unlink()
    return target


def import_keep_archive(
    archive_path: Path,
    state: Path,
    *,
    dry_run: bool,
    limit: int | None,
) -> dict[str, object]:
    inspection = inspect_keep_archive(archive_path)
    notes = inspection.pop("notes")
    assert isinstance(notes, list)
    selected = notes if limit is None else notes[:limit]
    result: dict[str, object] = {
        **inspection,
        "notes_found": len(notes),
        "notes_selected": len(selected),
        "dry_run": dry_run,
        "created": 0,
        "duplicates": 0,
        "archive_preserved": False,
    }
    if dry_run:
        return result

    if not state.is_dir():
        raise JarvisError("The configured state root is not a directory.")
    preserved = _preserve_archive(
        archive_path, state, str(inspection["archive_sha256"])
    )
    result["archive_preserved"] = True
    result["preserved_archive"] = preserved.relative_to(state).as_posix()
    for item in selected:
        created = capture_material(state, **item)
        if created["created"]:
            result["created"] = int(result["created"]) + 1
        else:
            result["duplicates"] = int(result["duplicates"]) + 1
    return result


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safely import Google Keep Takeout JSON notes into Jarvis captures."
    )
    parser.add_argument("archive", type=Path)
    parser.add_argument(
        "--state", type=Path, default=Path(os.environ.get("STATE_ROOT", "/state"))
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    if args.limit is not None and not 1 <= args.limit <= 10_000:
        parser.error("--limit must be between 1 and 10000")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = import_keep_archive(
            args.archive.resolve(strict=True),
            args.state.resolve(strict=True),
            dry_run=args.dry_run,
            limit=args.limit,
        )
    except (JarvisError, OSError, zipfile.BadZipFile) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
