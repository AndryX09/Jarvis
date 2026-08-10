from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable

MAX_WATCHED_FILE_BYTES = 1_000_000
MAX_WATCHER_STATE_BYTES = 64_000_000
MAX_AUDIT_LINE_BYTES = 16_384
MAX_RECENT_AUDIT_IDS = 10_000


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _open_regular_descriptor(path: Path, flags: int, mode: int = 0o600) -> int:
    safe_flags = flags
    if hasattr(os, "O_BINARY"):
        safe_flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        safe_flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, safe_flags, mode)
    except OSError as exc:
        if path.is_symlink():
            raise ValueError("Watcher file path is invalid.") from exc
        raise
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        os.close(descriptor)
        raise ValueError("Watcher file path is invalid.")
    return descriptor


def _read_preserved_blob(originals_root: Path, digest: str) -> bytes:
    target = originals_root / f"{digest}.md"
    if originals_root.is_symlink() or not originals_root.is_dir():
        raise ValueError("Watcher originals root is invalid.")
    if os.name != "nt" and hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd:
        directory_flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            directory_flags |= os.O_DIRECTORY
        directory_flags |= os.O_NOFOLLOW
        directory_descriptor = os.open(originals_root, directory_flags)
        try:
            file_descriptor = os.open(
                target.name,
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=directory_descriptor,
            )
            try:
                metadata = os.fstat(file_descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    raise ValueError("Preserved watcher content path is invalid.")
                if metadata.st_size > MAX_WATCHED_FILE_BYTES:
                    raise ValueError("Preserved watcher content exceeds size limit.")
                with os.fdopen(file_descriptor, "rb", closefd=False) as source:
                    content = source.read(MAX_WATCHED_FILE_BYTES + 1)
            finally:
                os.close(file_descriptor)
        finally:
            os.close(directory_descriptor)
        if len(content) > MAX_WATCHED_FILE_BYTES:
            raise ValueError("Preserved watcher content exceeds size limit.")
        return content
    return VaultWatcher._read_regular_file(target)


@dataclass(frozen=True)
class WatchEvent:
    event_type: str
    relative_path: str
    previous_sha256: str | None
    sha256: str | None
    sequence: int = 0

    @property
    def event_id(self) -> str:
        identity = json.dumps(
            {
                "event_type": self.event_type,
                "relative_path": self.relative_path,
                "previous_sha256": self.previous_sha256,
                "sequence": self.sequence,
                "sha256": self.sha256,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(identity).hexdigest()


class VaultWatcher:
    def __init__(self, vault_root: Path, *, state_root: Path | None = None):
        self._vault_root = vault_root.resolve(strict=True)
        self._vault_root_identity = os.stat(
            self._vault_root,
            follow_symlinks=False,
        )
        resolved_state_root = (
            state_root.resolve(strict=True) if state_root is not None else None
        )
        if resolved_state_root is not None and (
            self._is_within(resolved_state_root, self._vault_root)
            or self._is_within(self._vault_root, resolved_state_root)
        ):
            raise ValueError("Watcher vault and state roots must not overlap.")
        self._audit_path = (
            resolved_state_root / "watcher-events.jsonl"
            if resolved_state_root is not None
            else None
        )
        self._state_path = (
            resolved_state_root / "watcher-state.json"
            if resolved_state_root is not None
            else None
        )
        self._originals_root = (
            resolved_state_root / "watcher-originals"
            if resolved_state_root is not None
            else None
        )
        self._outbox_path = (
            resolved_state_root / "watcher-outbox.json"
            if resolved_state_root is not None
            else None
        )
        self._next_sequence = 1
        self._last_audited_sequence = 0
        self._audited_event_ids = self._load_audited_event_ids()
        self._outbox = self._load_outbox()
        if self._originals_root is not None:
            if self._originals_root.exists():
                if self._originals_root.is_symlink() or not self._originals_root.is_dir():
                    raise ValueError("Watcher originals root is invalid.")
            else:
                self._originals_root.mkdir()
                _fsync_directory(self._originals_root.parent)
        if self._state_path is not None and self._state_path.is_symlink():
            raise ValueError("Watcher state is invalid.")
        if self._state_path is not None and self._state_path.exists():
            self._snapshot = self._load_snapshot()
        else:
            self._snapshot, contents = self._scan()
            for relative_path, digest in self._snapshot.items():
                self._preserve_content(digest, contents[relative_path])
            self._save_snapshot()
        self._pending: dict[str, str | None] = {}

    def poll(
        self,
        on_event: Callable[[WatchEvent], object] | None = None,
    ) -> list[WatchEvent]:
        events: list[WatchEvent] = []
        if on_event is not None:
            if self._outbox_path is None:
                raise ValueError("Watcher callbacks require a durable state root.")
            events.extend(self._replay_outbox(on_event))

        current, contents = self._scan()

        for relative_path in sorted(self._snapshot.keys() | current.keys()):
            previous_sha256 = self._snapshot.get(relative_path)
            current_sha256 = current.get(relative_path)

            if previous_sha256 == current_sha256:
                self._pending.pop(relative_path, None)
                continue

            if (
                relative_path not in self._pending
                or self._pending[relative_path] != current_sha256
            ):
                self._pending[relative_path] = current_sha256
                continue

            if previous_sha256 is None:
                event_type = "created"
            elif current_sha256 is None:
                event_type = "deleted"
            else:
                event_type = "modified"

            event = WatchEvent(
                event_type=event_type,
                relative_path=relative_path,
                previous_sha256=previous_sha256,
                sha256=current_sha256,
                sequence=self._allocate_sequence(),
            )
            if current_sha256 is not None:
                self._preserve_content(
                    current_sha256,
                    contents[relative_path],
                )
            self._verify_event_blobs(event)
            if on_event is not None:
                self._enqueue_event(event)
            self._append_audit(event)
            if on_event is not None:
                on_event(event)
            events.append(event)
            self._apply_event(event)
            if on_event is not None:
                self._dequeue_event(event)
            self._pending.pop(relative_path, None)

        return events

    def _replay_outbox(
        self,
        on_event: Callable[[WatchEvent], object],
    ) -> list[WatchEvent]:
        replayed: list[WatchEvent] = []
        for event in tuple(self._outbox):
            self._verify_event_blobs(event)
            self._append_audit(event)
            on_event(event)
            self._apply_event(event)
            self._dequeue_event(event)
            self._pending.pop(event.relative_path, None)
            replayed.append(event)
        return replayed

    def _verify_event_blobs(self, event: WatchEvent) -> None:
        if event.previous_sha256 is not None:
            self._verify_preserved_content(event.previous_sha256)
        if event.sha256 is not None:
            self._verify_preserved_content(event.sha256)

    def _apply_event(self, event: WatchEvent) -> None:
        current_digest = self._snapshot.get(event.relative_path)
        if current_digest not in {event.previous_sha256, event.sha256}:
            raise ValueError("Watcher outbox conflicts with durable snapshot.")
        previous_snapshot = self._snapshot
        self._snapshot = dict(previous_snapshot)
        try:
            if event.sha256 is None:
                self._snapshot.pop(event.relative_path, None)
            else:
                self._snapshot[event.relative_path] = event.sha256
            self._save_snapshot()
        except BaseException:
            self._snapshot = previous_snapshot
            raise

    def _enqueue_event(self, event: WatchEvent) -> None:
        if any(queued.event_id == event.event_id for queued in self._outbox):
            return
        previous_outbox = self._outbox
        self._outbox = [*previous_outbox, event]
        try:
            self._save_outbox()
        except BaseException:
            self._outbox = previous_outbox
            raise

    def _dequeue_event(self, event: WatchEvent) -> None:
        previous_outbox = self._outbox
        self._outbox = [
            queued for queued in self._outbox if queued.event_id != event.event_id
        ]
        try:
            self._save_outbox()
        except BaseException:
            self._outbox = previous_outbox
            raise

    def _load_outbox(self) -> list[WatchEvent]:
        if self._outbox_path is None:
            return []
        if self._outbox_path.is_symlink():
            raise ValueError("Watcher outbox is invalid.")
        if not self._outbox_path.exists():
            return []
        try:
            data = self._read_regular_file(
                self._outbox_path,
                max_bytes=MAX_WATCHER_STATE_BYTES,
            )
            records = json.loads(data.decode("utf-8"))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Watcher outbox is invalid.") from exc
        if not isinstance(records, list):
            raise ValueError("Watcher outbox is invalid.")

        events: list[WatchEvent] = []
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("Watcher outbox is invalid.")
            try:
                event = WatchEvent(
                    event_type=record["event_type"],
                    relative_path=record["relative_path"],
                    previous_sha256=record["previous_sha256"],
                    sha256=record["sha256"],
                    sequence=record["sequence"],
                )
            except KeyError as exc:
                raise ValueError("Watcher outbox is invalid.") from exc
            if record.get("event_id") != event.event_id or not self._valid_event(event):
                raise ValueError("Watcher outbox is invalid.")
            events.append(event)
            self._next_sequence = max(self._next_sequence, event.sequence + 1)
        if len({event.event_id for event in events}) != len(events):
            raise ValueError("Watcher outbox is invalid.")
        if any(
            current.sequence <= previous.sequence
            for previous, current in zip(events, events[1:])
        ):
            raise ValueError("Watcher outbox is invalid.")
        return events

    def _save_outbox(self) -> None:
        assert self._outbox_path is not None
        if self._outbox_path.exists() and (
            self._outbox_path.is_symlink() or not self._outbox_path.is_file()
        ):
            raise ValueError("Watcher outbox is invalid.")
        records = [
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "relative_path": event.relative_path,
                "previous_sha256": event.previous_sha256,
                "sequence": event.sequence,
                "sha256": event.sha256,
            }
            for event in self._outbox
        ]
        payload = json.dumps(records, ensure_ascii=False, sort_keys=True) + "\n"
        if len(payload.encode("utf-8")) > MAX_WATCHER_STATE_BYTES:
            raise ValueError("Watcher outbox exceeds size limit.")
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self._outbox_path.parent,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self._outbox_path)
            _fsync_directory(self._outbox_path.parent)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _append_audit(self, event: WatchEvent) -> None:
        if self._audit_path is None:
            return
        if self._audit_path.is_symlink():
            raise ValueError("Watcher audit path is invalid.")
        if not self._valid_event(event):
            raise ValueError("Watcher audit event is invalid.")
        if event.event_id in self._audited_event_ids:
            return
        if (
            event.sequence <= self._last_audited_sequence
            and self._audit_path.exists()
            and self._audit_contains(event)
        ):
            self._remember_audited_event(event.event_id)
            return
        if event.sequence <= self._last_audited_sequence:
            raise ValueError("Watcher audit sequence is invalid.")

        record = {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "relative_path": event.relative_path,
            "previous_sha256": event.previous_sha256,
            "sequence": event.sequence,
            "sha256": event.sha256,
            "timestamp_utc": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        }
        line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        if len(line.encode("utf-8")) > MAX_AUDIT_LINE_BYTES:
            raise ValueError("Watcher audit event exceeds size limit.")
        descriptor = _open_regular_descriptor(
            self._audit_path,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT,
        )
        with os.fdopen(descriptor, "a", encoding="utf-8", newline="\n") as audit:
            audit.write(line)
            audit.flush()
            os.fsync(audit.fileno())
        _fsync_directory(self._audit_path.parent)
        self._last_audited_sequence = event.sequence
        self._remember_audited_event(event.event_id)

    def _load_audited_event_ids(self) -> OrderedDict[str, None]:
        if self._audit_path is None:
            return OrderedDict()
        if self._audit_path.is_symlink():
            raise ValueError("Watcher audit is invalid.")
        if not self._audit_path.exists():
            return OrderedDict()
        if (
            self._audit_path.is_symlink()
            or not self._audit_path.is_file()
        ):
            raise ValueError("Watcher audit is invalid.")

        event_ids: OrderedDict[str, None] = OrderedDict()
        for event_id, sequence in self._iter_audit_event_ids():
            if sequence <= self._last_audited_sequence:
                raise ValueError("Watcher audit is invalid.")
            self._last_audited_sequence = sequence
            self._next_sequence = max(self._next_sequence, sequence + 1)
            event_ids[event_id] = None
            event_ids.move_to_end(event_id)
            if len(event_ids) > MAX_RECENT_AUDIT_IDS:
                event_ids.popitem(last=False)
        return event_ids

    def _audit_contains(self, expected_event: WatchEvent) -> bool:
        found = False
        for event_id, sequence in self._iter_audit_event_ids():
            if sequence == expected_event.sequence and event_id != expected_event.event_id:
                raise ValueError("Watcher audit is invalid.")
            if event_id == expected_event.event_id:
                found = True
        return found

    def _remember_audited_event(self, event_id: str) -> None:
        self._audited_event_ids[event_id] = None
        self._audited_event_ids.move_to_end(event_id)
        if len(self._audited_event_ids) > MAX_RECENT_AUDIT_IDS:
            self._audited_event_ids.popitem(last=False)

    def _iter_audit_event_ids(self):
        if self._audit_path is None:
            return
        try:
            descriptor = _open_regular_descriptor(self._audit_path, os.O_RDONLY)
            with os.fdopen(descriptor, "rb") as audit:
                while True:
                    line = audit.readline(MAX_AUDIT_LINE_BYTES + 1)
                    if not line:
                        break
                    if len(line) > MAX_AUDIT_LINE_BYTES or not line.endswith(b"\n"):
                        raise ValueError("Watcher audit is invalid.")
                    try:
                        record = json.loads(line.decode("utf-8"))
                        event_id = record["event_id"]
                        sequence = record["sequence"]
                    except (
                        KeyError,
                        TypeError,
                        UnicodeError,
                        json.JSONDecodeError,
                    ) as exc:
                        raise ValueError("Watcher audit is invalid.") from exc
                    if (
                        not isinstance(record, dict)
                        or not isinstance(event_id, str)
                        or len(event_id) != 64
                        or not isinstance(sequence, int)
                        or isinstance(sequence, bool)
                        or sequence <= 0
                        or any(
                            character not in "0123456789abcdef"
                            for character in event_id
                        )
                    ):
                        raise ValueError("Watcher audit is invalid.")
                    yield event_id, sequence
        except (OSError, UnicodeError) as exc:
            raise ValueError("Watcher audit is invalid.") from exc

    def _load_snapshot(self) -> dict[str, str]:
        assert self._state_path is not None
        try:
            data = self._read_regular_file(
                self._state_path,
                max_bytes=MAX_WATCHER_STATE_BYTES,
            )
            snapshot = json.loads(data.decode("utf-8"))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Watcher state is invalid.") from exc
        if not isinstance(snapshot, dict) or not all(
            isinstance(path, str)
            and self._valid_relative_markdown_path(path)
            and isinstance(digest, str)
            and len(digest) == 64
            and all(character in "0123456789abcdef" for character in digest)
            for path, digest in snapshot.items()
        ):
            raise ValueError("Watcher state is invalid.")
        return snapshot

    def _save_snapshot(self) -> None:
        if self._state_path is None:
            return

        payload = json.dumps(
            self._snapshot,
            ensure_ascii=False,
            sort_keys=True,
        ) + "\n"
        if len(payload.encode("utf-8")) > MAX_WATCHER_STATE_BYTES:
            raise ValueError("Watcher state exceeds size limit.")
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self._state_path.parent,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self._state_path)
            _fsync_directory(self._state_path.parent)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _preserve_content(self, digest: str, content: bytes) -> None:
        if self._originals_root is None:
            return
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("Watcher content does not match its digest.")

        target = self._originals_root / f"{digest}.md"
        if target.exists():
            self._verify_preserved_content(digest)
            return

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "wb",
                dir=self._originals_root,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, target)
            _fsync_directory(target.parent)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _verify_preserved_content(self, digest: str) -> None:
        if self._originals_root is None:
            return
        target = self._originals_root / f"{digest}.md"
        if target.is_symlink() or not target.exists():
            raise ValueError("Preserved watcher content is unavailable or invalid.")
        existing = _read_preserved_blob(self._originals_root, digest)
        if hashlib.sha256(existing).hexdigest() != digest:
            raise ValueError("Preserved watcher content is corrupt.")

    def _scan(self) -> tuple[dict[str, str], dict[str, bytes]]:
        snapshot = {}
        contents = {}

        for path in self._vault_root.rglob("*"):
            relative = path.relative_to(self._vault_root)

            if (
                path.suffix.casefold() != ".md"
                or path.is_symlink()
                or not path.is_file()
                or any(
                    part.startswith(".") for part in relative.parts
                )
            ):
                continue

            relative_path = relative.as_posix()
            content = self._read_vault_file(relative)
            snapshot[relative_path] = hashlib.sha256(content).hexdigest()
            contents[relative_path] = content

        return snapshot, contents

    def _read_vault_file(self, relative_path: Path) -> bytes:
        if (
            os.name != "nt"
            and hasattr(os, "O_NOFOLLOW")
            and os.open in os.supports_dir_fd
        ):
            directory_flags = os.O_RDONLY | os.O_NOFOLLOW
            if hasattr(os, "O_DIRECTORY"):
                directory_flags |= os.O_DIRECTORY
            root_descriptor = os.open(self._vault_root, directory_flags)
            current_descriptor = root_descriptor
            try:
                if not os.path.samestat(
                    os.fstat(root_descriptor),
                    self._vault_root_identity,
                ):
                    raise ValueError("Watcher file path is invalid.")
                for part in relative_path.parts[:-1]:
                    next_descriptor = os.open(
                        part,
                        directory_flags,
                        dir_fd=current_descriptor,
                    )
                    if current_descriptor != root_descriptor:
                        os.close(current_descriptor)
                    current_descriptor = next_descriptor
                file_descriptor = os.open(
                    relative_path.name,
                    os.O_RDONLY | os.O_NOFOLLOW,
                    dir_fd=current_descriptor,
                )
                try:
                    return self._read_open_descriptor(file_descriptor)
                finally:
                    os.close(file_descriptor)
            except OSError as exc:
                raise ValueError("Watcher file path is invalid.") from exc
            finally:
                if current_descriptor != root_descriptor:
                    os.close(current_descriptor)
                os.close(root_descriptor)

        path = self._vault_root.joinpath(*relative_path.parts)
        descriptor = _open_regular_descriptor(path, os.O_RDONLY)
        try:
            metadata = os.fstat(descriptor)
            self._validate_open_vault_path(path, relative_path, metadata)
            return self._read_open_descriptor(descriptor)
        finally:
            os.close(descriptor)

    def _validate_open_vault_path(
        self,
        path: Path,
        relative_path: Path,
        metadata: os.stat_result,
    ) -> None:
        try:
            current_root_identity = os.stat(
                self._vault_root,
                follow_symlinks=False,
            )
            if self._vault_root.is_symlink() or not os.path.samestat(
                current_root_identity,
                self._vault_root_identity,
            ):
                raise ValueError("Watcher file path is invalid.")
            ancestor = self._vault_root
            for part in relative_path.parts[:-1]:
                ancestor /= part
                if ancestor.is_symlink() or not ancestor.is_dir():
                    raise ValueError("Watcher file path is invalid.")
            path_identity = os.stat(path, follow_symlinks=False)
            if not os.path.samestat(metadata, path_identity):
                raise ValueError("Watcher file path is invalid.")
        except OSError as exc:
            raise ValueError("Watcher file path is invalid.") from exc

    @staticmethod
    def _read_open_descriptor(
        descriptor: int,
        max_bytes: int = MAX_WATCHED_FILE_BYTES,
    ) -> bytes:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("Watcher file path is invalid.")
        if metadata.st_size > max_bytes:
            raise ValueError("Watcher file exceeds size limit.")
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            content = source.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise ValueError("Watcher file exceeds size limit.")
        return content

    @staticmethod
    def _read_regular_file(
        path: Path,
        *,
        max_bytes: int = MAX_WATCHED_FILE_BYTES,
    ) -> bytes:
        descriptor = _open_regular_descriptor(path, os.O_RDONLY)
        try:
            return VaultWatcher._read_open_descriptor(descriptor, max_bytes)
        finally:
            os.close(descriptor)

    @staticmethod
    def _valid_relative_markdown_path(value: str) -> bool:
        path = PurePosixPath(value)
        return (
            bool(value)
            and path.as_posix() == value
            and not path.is_absolute()
            and path.suffix.casefold() == ".md"
            and all(
                part not in {"", ".", ".."} and not part.startswith(".")
                for part in path.parts
            )
        )

    @classmethod
    def _valid_event(cls, event: WatchEvent) -> bool:
        if (
            event.event_type not in {"created", "modified", "deleted"}
            or not isinstance(event.relative_path, str)
            or not cls._valid_relative_markdown_path(event.relative_path)
            or not isinstance(event.sequence, int)
            or isinstance(event.sequence, bool)
            or event.sequence <= 0
        ):
            return False
        previous_is_digest = cls._valid_digest(event.previous_sha256)
        current_is_digest = cls._valid_digest(event.sha256)
        return (
            event.event_type == "created"
            and event.previous_sha256 is None
            and current_is_digest
        ) or (
            event.event_type == "modified"
            and previous_is_digest
            and current_is_digest
            and event.previous_sha256 != event.sha256
        ) or (
            event.event_type == "deleted"
            and previous_is_digest
            and event.sha256 is None
        )

    @staticmethod
    def _valid_digest(value: object) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )

    def _allocate_sequence(self) -> int:
        sequence = self._next_sequence
        self._next_sequence += 1
        return sequence

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        return path == root or root in path.parents