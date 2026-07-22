#!/usr/bin/env python3
"""Fail-closed helpers for verifying and activating a Jarvis release."""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Callable


class ReleaseError(RuntimeError):
    """Raised when a release safety check fails."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_replace_bytes(destination: Path, data: bytes, mode: int) -> None:
    destination = Path(destination)
    parent = destination.parent
    if not parent.is_dir() or parent.is_symlink():
        raise ReleaseError("Launcher destination parent is unsafe.")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".candidate", dir=parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(mode)
        os.replace(temporary, destination)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ReleaseError("Atomic launcher write failed.") from exc


def render_launcher(
    template_path: Path,
    expected_template_sha256: str,
    image_id: str,
    destination_path: Path,
) -> str:
    """Render one pinned launcher template with an immutable Docker image ID."""
    template_data = Path(template_path).read_bytes()
    if _sha256(template_data) != expected_template_sha256:
        raise ReleaseError("Launcher template SHA-256 does not match the pinned value.")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        raise ReleaseError("Launcher requires an immutable Docker image ID.")
    placeholder = b"IMAGE_ID_PLACEHOLDER"
    if template_data.count(placeholder) != 1:
        raise ReleaseError("Launcher template must contain exactly one image placeholder.")
    rendered = template_data.replace(placeholder, image_id.encode("ascii"))
    _atomic_replace_bytes(Path(destination_path), rendered, 0o750)
    return _sha256(rendered)


def _verify_launcher_data(data: bytes, expected_sha256: str, image_id: str) -> None:
    if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        raise ReleaseError("Launcher verification requires an immutable image ID.")
    if _sha256(data) != expected_sha256:
        raise ReleaseError("Launcher SHA-256 does not match the expected value.")
    if data.count(image_id.encode("ascii")) != 1 or b"IMAGE_ID_PLACEHOLDER" in data:
        raise ReleaseError("Launcher does not contain exactly the expected image ID.")


def verify_launcher(path: Path, expected_sha256: str, image_id: str) -> Path:
    """Verify one active launcher against exact bytes and one immutable image ID."""
    launcher = Path(path)
    if not launcher.is_file() or launcher.is_symlink():
        raise ReleaseError("Launcher is missing or unsafe.")
    _verify_launcher_data(launcher.read_bytes(), expected_sha256, image_id)
    return launcher


def restore_launcher(
    source_path: Path,
    expected_sha256: str,
    image_id: str,
    active_path: Path,
) -> Path:
    """Atomically restore and verify a pinned launcher regardless of active contents."""
    source_data = Path(source_path).read_bytes()
    _verify_launcher_data(source_data, expected_sha256, image_id)
    active = Path(active_path)
    _atomic_replace_bytes(active, source_data, 0o750)
    verify_launcher(active, expected_sha256, image_id)
    return active


def activate_launcher(
    source_path: Path,
    expected_source_sha256: str,
    rollback_path: Path,
    expected_rollback_sha256: str,
    installed_path: Path,
    active_path: Path,
    post_replace_verifier: Callable[[Path], bool] | None = None,
) -> Path:
    """Atomically activate a verified launcher and restore rollback on failure."""
    source_data = Path(source_path).read_bytes()
    rollback_data = Path(rollback_path).read_bytes()
    if _sha256(source_data) != expected_source_sha256:
        raise ReleaseError("New launcher SHA-256 does not match the pinned value.")
    if _sha256(rollback_data) != expected_rollback_sha256:
        raise ReleaseError("Rollback launcher SHA-256 does not match the pinned value.")
    active = Path(active_path)
    if not active.is_file() or active.is_symlink():
        raise ReleaseError("Active launcher is missing or unsafe.")
    if _sha256(active.read_bytes()) != expected_rollback_sha256:
        raise ReleaseError("Active launcher is not the expected rollback version.")

    _atomic_replace_bytes(Path(installed_path), source_data, 0o750)
    _atomic_replace_bytes(active, source_data, 0o750)
    verifier = post_replace_verifier or (
        lambda path: _sha256(path.read_bytes()) == expected_source_sha256
    )
    try:
        verified = bool(verifier(active))
    except Exception:
        verified = False
    if not verified:
        _atomic_replace_bytes(active, rollback_data, 0o750)
        if _sha256(active.read_bytes()) != expected_rollback_sha256:
            raise ReleaseError("Launcher verification failed and rollback restoration failed.")
        raise ReleaseError("Launcher verification failed; rollback was restored.")
    return active


def snapshot_names(backups_root: Path) -> set[str]:
    root = Path(backups_root)
    if not root.is_dir() or root.is_symlink():
        raise ReleaseError("Backup root must be an existing real directory.")
    return {
        candidate.name
        for candidate in root.iterdir()
        if re.fullmatch(r"20\d{6}T\d{6}Z", candidate.name)
        and candidate.is_dir()
        and not candidate.is_symlink()
    }


def verify_new_snapshot(
    backups_root: Path,
    before_names: set[str],
    expected_source_vault: str,
    expected_source_state: str,
) -> Path:
    """Require exactly one new snapshot after a backup command."""
    created = snapshot_names(backups_root) - set(before_names)
    if len(created) != 1:
        raise ReleaseError("Backup command did not create exactly one new snapshot.")
    snapshot_name = next(iter(created))
    snapshot = Path(backups_root) / snapshot_name
    manifest_path = snapshot / "MANIFEST.txt"
    sums_path = snapshot / "SHA256SUMS"
    for required in (manifest_path, sums_path):
        if not required.is_file() or required.is_symlink():
            raise ReleaseError("New snapshot metadata is missing or unsafe.")

    try:
        manifest_lines = manifest_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ReleaseError("New snapshot manifest is unreadable.") from exc
    manifest: dict[str, str] = {}
    for line in manifest_lines:
        match = re.fullmatch(r"([a-z_]+)=(.*)", line)
        if match is None or match.group(1) in manifest:
            raise ReleaseError("New snapshot manifest is invalid.")
        manifest[match.group(1)] = match.group(2)
    if set(manifest) != {
        "created_utc",
        "source_vault",
        "source_state",
        "previous_snapshot",
    }:
        raise ReleaseError("New snapshot manifest fields are invalid.")
    if manifest["created_utc"] != snapshot_name:
        raise ReleaseError("New snapshot timestamp does not match its directory.")
    if manifest["source_vault"] != expected_source_vault:
        raise ReleaseError("New snapshot records an unexpected vault source.")
    if manifest["source_state"] != expected_source_state:
        raise ReleaseError("New snapshot records an unexpected state source.")
    previous = manifest["previous_snapshot"]
    if previous != "none" and previous not in before_names:
        raise ReleaseError("New snapshot records an unexpected predecessor.")

    payload: dict[str, bytes] = {}
    payload_directories: set[str] = set()
    for area in ("vault", "state"):
        area_root = snapshot / area
        if not area_root.is_dir() or area_root.is_symlink():
            raise ReleaseError("New snapshot payload directory is missing or unsafe.")
        payload_directories.add(area)
        for candidate in area_root.rglob("*"):
            if candidate.is_symlink():
                raise ReleaseError("New snapshot payload contains a symbolic link.")
            if candidate.is_file():
                relative = candidate.relative_to(snapshot).as_posix()
                payload[relative] = candidate.read_bytes()
            elif candidate.is_dir():
                payload_directories.add(candidate.relative_to(snapshot).as_posix())
            else:
                raise ReleaseError("New snapshot payload contains an unsafe file type.")

    if not payload:
        raise ReleaseError("New snapshot payload is empty and cannot match live sources.")

    try:
        sum_lines = sums_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ReleaseError("New snapshot checksum list is unreadable.") from exc
    expected: dict[str, str] = {}
    for line in sum_lines:
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if match is None:
            raise ReleaseError("New snapshot checksum line is invalid.")
        digest, name = match.groups()
        normalized = _safe_manifest_path(name).as_posix()
        if not normalized.startswith(("vault/", "state/")) or normalized in expected:
            raise ReleaseError("New snapshot checksum path is invalid.")
        expected[normalized] = digest
    if set(expected) != set(payload):
        raise ReleaseError("New snapshot checksum inventory is incomplete.")
    for relative, data in payload.items():
        if _sha256(data) != expected[relative]:
            raise ReleaseError(f"New snapshot checksum mismatch: {relative}")

    live_payload: dict[str, bytes] = {}
    live_directories: set[str] = set()
    live_roots = {
        "vault": (Path(expected_source_vault), {".stfolder", ".stignore", ".stversions"}),
        "state": (Path(expected_source_state), set()),
    }
    for area, (live_root, excluded_top_levels) in live_roots.items():
        if not live_root.is_dir() or live_root.is_symlink():
            raise ReleaseError("Live backup source is missing or unsafe.")
        live_directories.add(area)
        for candidate in live_root.rglob("*"):
            relative_to_live = candidate.relative_to(live_root)
            if relative_to_live.parts[0] in excluded_top_levels:
                continue
            if candidate.is_symlink():
                raise ReleaseError("Live backup source contains a symbolic link.")
            relative = PurePosixPath(area, *relative_to_live.parts).as_posix()
            if candidate.is_file():
                live_payload[relative] = candidate.read_bytes()
            elif candidate.is_dir():
                live_directories.add(relative)
            else:
                raise ReleaseError("Live backup source contains an unsafe file type.")

    if set(live_payload) != set(payload) or live_directories != payload_directories:
        raise ReleaseError("New snapshot inventory does not match the live sources.")
    for relative, live_data in live_payload.items():
        if live_data != payload[relative]:
            raise ReleaseError(f"New snapshot does not match live file: {relative}")
    return snapshot


def _safe_member_path(name: str, release_dir_name: str) -> PurePosixPath:
    if not isinstance(name, str) or not name or "\\" in name:
        raise ReleaseError("Archive member path is invalid.")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ReleaseError("Archive member escapes the release directory.")
    if not path.parts or path.parts[0] != release_dir_name:
        raise ReleaseError("Archive member has an unexpected release prefix.")
    return path


def _safe_manifest_path(name: str) -> PurePosixPath:
    if not name or "\\" in name:
        raise ReleaseError("Source manifest path is invalid.")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ReleaseError("Source manifest path escapes the release directory.")
    return path


def _parse_source_manifest(data: bytes) -> tuple[dict[str, str], set[str]]:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ReleaseError("Source manifest is not UTF-8 text.") from exc
    entries: dict[str, str] = {}
    directories: set[str] = set()
    for line in lines:
        directory_match = re.fullmatch(r"directory  (.+)", line)
        file_match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if (directory_match is None) == (file_match is None):
            raise ReleaseError("Source manifest line is invalid.")
        if directory_match is not None:
            name = directory_match.group(1)
            digest = None
        else:
            assert file_match is not None
            digest, name = file_match.groups()
        normalized = _safe_manifest_path(name).as_posix()
        if (
            normalized == "SOURCE-SHA256SUMS"
            or normalized in entries
            or normalized in directories
        ):
            raise ReleaseError("Source manifest contains a duplicate or reserved path.")
        if digest is None:
            directories.add(normalized)
        else:
            entries[normalized] = digest
    return entries, directories


def extract_verified_archive(
    archive_path: Path,
    expected_archive_sha256: str,
    expected_manifest_sha256: str,
    destination_parent: Path,
    release_dir_name: str,
) -> Path:
    """Validate a release archive from one in-memory read before extraction."""
    archive_data = Path(archive_path).read_bytes()
    if _sha256(archive_data) != expected_archive_sha256:
        raise ReleaseError("Archive SHA-256 does not match the pinned value.")

    try:
        with tarfile.open(fileobj=io.BytesIO(archive_data), mode="r:gz") as bundle:
            regular_members: dict[str, tarfile.TarInfo] = {}
            directory_members: set[str] = set()
            all_member_paths: set[str] = set()
            verified_contents: dict[str, bytes] = {}
            for member in bundle.getmembers():
                member_path = _safe_member_path(member.name, release_dir_name)
                relative = PurePosixPath(*member_path.parts[1:]).as_posix()
                if relative in ("", ".") or relative in all_member_paths:
                    raise ReleaseError("Archive contains a duplicate or empty member path.")
                all_member_paths.add(relative)
                if member.isreg():
                    regular_members[relative] = member
                elif member.isdir():
                    directory_members.add(relative)
                else:
                    raise ReleaseError(
                        "Archive may contain only declared directories and regular files."
                    )

            regular_paths = set(regular_members)
            for relative in all_member_paths:
                parts = PurePosixPath(relative).parts
                if any(
                    PurePosixPath(*parts[:index]).as_posix() in regular_paths
                    for index in range(1, len(parts))
                ):
                    raise ReleaseError("Archive contains a file path prefix collision.")

            manifest_member = regular_members.get("SOURCE-SHA256SUMS")
            if manifest_member is None:
                raise ReleaseError("Archive source manifest is missing.")
            manifest_file = bundle.extractfile(manifest_member)
            if manifest_file is None:
                raise ReleaseError("Archive source manifest is unreadable.")
            manifest_data = manifest_file.read()
            if _sha256(manifest_data) != expected_manifest_sha256:
                raise ReleaseError("Source manifest SHA-256 does not match the pinned value.")
            expected_files, expected_directories = _parse_source_manifest(manifest_data)
            actual_files = set(regular_members) - {"SOURCE-SHA256SUMS"}
            if (
                actual_files != set(expected_files)
                or directory_members != expected_directories
            ):
                raise ReleaseError("Archive member inventory does not match the manifest.")
            for relative in [*expected_files, *expected_directories]:
                parts = PurePosixPath(relative).parts
                required_parents = {
                    PurePosixPath(*parts[:index]).as_posix()
                    for index in range(1, len(parts))
                }
                if not required_parents.issubset(expected_directories):
                    raise ReleaseError("Archive directory hierarchy is not fully declared.")
            for relative, expected_hash in expected_files.items():
                source = bundle.extractfile(regular_members[relative])
                if source is None:
                    raise ReleaseError(f"Source file is unreadable: {relative}")
                content = source.read()
                if _sha256(content) != expected_hash:
                    raise ReleaseError(f"Source file hash mismatch: {relative}")
                verified_contents[relative] = content
    except (tarfile.TarError, OSError) as exc:
        raise ReleaseError("Archive is unreadable.") from exc

    release_name = _safe_manifest_path(release_dir_name)
    if len(release_name.parts) != 1:
        raise ReleaseError("Release directory name must contain one path component.")
    parent = Path(destination_parent)
    if not parent.is_dir() or parent.is_symlink():
        raise ReleaseError("Destination parent must be an existing real directory.")
    target = parent / release_dir_name
    if target.exists() or target.is_symlink():
        raise ReleaseError("Release destination already exists.")

    all_contents = dict(verified_contents)
    all_contents["SOURCE-SHA256SUMS"] = manifest_data
    staging = Path(
        tempfile.mkdtemp(prefix=f".{release_dir_name}.partial-", dir=parent)
    )
    try:
        staging.chmod(0o755)
        for relative in sorted(
            expected_directories,
            key=lambda value: (len(PurePosixPath(value).parts), value),
        ):
            staging.joinpath(*PurePosixPath(relative).parts).mkdir(mode=0o755)
        for relative, content in sorted(all_contents.items()):
            destination = staging.joinpath(*PurePosixPath(relative).parts)
            with destination.open("xb") as handle:
                handle.write(content)
            destination.chmod(0o644)
        if target.exists() or target.is_symlink():
            raise ReleaseError("Release destination appeared during extraction.")
        os.rename(staging, target)
    except ReleaseError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise ReleaseError("Verified source extraction failed.") from exc
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    snapshot_list = commands.add_parser("snapshot-list")
    snapshot_list.add_argument("backups_root", type=Path)

    snapshot_verify = commands.add_parser("verify-new-snapshot")
    snapshot_verify.add_argument("backups_root", type=Path)
    snapshot_verify.add_argument("before_file", type=Path)
    snapshot_verify.add_argument("expected_source_vault")
    snapshot_verify.add_argument("expected_source_state")

    extract = commands.add_parser("extract")
    extract.add_argument("archive", type=Path)
    extract.add_argument("archive_sha256")
    extract.add_argument("manifest_sha256")
    extract.add_argument("destination_parent", type=Path)
    extract.add_argument("release_dir_name")

    render = commands.add_parser("render-launcher")
    render.add_argument("template", type=Path)
    render.add_argument("template_sha256")
    render.add_argument("image_id")
    render.add_argument("destination", type=Path)

    verify = commands.add_parser("verify-launcher")
    verify.add_argument("launcher", type=Path)
    verify.add_argument("launcher_sha256")
    verify.add_argument("image_id")

    restore = commands.add_parser("restore-launcher")
    restore.add_argument("source", type=Path)
    restore.add_argument("source_sha256")
    restore.add_argument("image_id")
    restore.add_argument("active", type=Path)

    activate = commands.add_parser("activate")
    activate.add_argument("source", type=Path)
    activate.add_argument("source_sha256")
    activate.add_argument("rollback", type=Path)
    activate.add_argument("rollback_sha256")
    activate.add_argument("installed", type=Path)
    activate.add_argument("active", type=Path)

    args = parser.parse_args(argv)
    try:
        if args.command == "snapshot-list":
            for name in sorted(snapshot_names(args.backups_root)):
                print(name)
        elif args.command == "verify-new-snapshot":
            before = set(args.before_file.read_text(encoding="utf-8").splitlines())
            print(
                verify_new_snapshot(
                    args.backups_root,
                    before,
                    args.expected_source_vault,
                    args.expected_source_state,
                )
            )
        elif args.command == "extract":
            print(
                extract_verified_archive(
                    args.archive,
                    args.archive_sha256,
                    args.manifest_sha256,
                    args.destination_parent,
                    args.release_dir_name,
                )
            )
        elif args.command == "render-launcher":
            print(
                render_launcher(
                    args.template,
                    args.template_sha256,
                    args.image_id,
                    args.destination,
                )
            )
        elif args.command == "verify-launcher":
            print(
                verify_launcher(
                    args.launcher,
                    args.launcher_sha256,
                    args.image_id,
                )
            )
        elif args.command == "restore-launcher":
            print(
                restore_launcher(
                    args.source,
                    args.source_sha256,
                    args.image_id,
                    args.active,
                )
            )
        elif args.command == "activate":
            print(
                activate_launcher(
                    args.source,
                    args.source_sha256,
                    args.rollback,
                    args.rollback_sha256,
                    args.installed,
                    args.active,
                )
            )
    except (ReleaseError, OSError, UnicodeError) as exc:
        print(f"ERRORE: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
