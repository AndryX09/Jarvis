import hashlib
import io
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from release_helpers import (
    ReleaseError,
    activate_launcher,
    extract_verified_archive,
    render_launcher,
    restore_launcher,
    verify_launcher,
    verify_new_snapshot,
)


def build_release_archive(
    archive: Path,
    declared_files: dict[str, bytes],
    extra_files: dict[str, bytes] | None = None,
) -> tuple[str, str]:
    directories = {
        Path(*Path(name).parts[:index]).as_posix()
        for name in declared_files
        for index in range(1, len(Path(name).parts))
    }
    manifest = (
        "".join(f"directory  {name}\n" for name in sorted(directories))
        + "".join(
            f"{hashlib.sha256(content).hexdigest()}  {name}\n"
            for name, content in sorted(declared_files.items())
        )
    ).encode("utf-8")
    members = dict(declared_files)
    members.update(extra_files or {})
    members["SOURCE-SHA256SUMS"] = manifest
    with tarfile.open(archive, "w:gz") as bundle:
        for name in sorted(directories):
            info = tarfile.TarInfo(f"jarvis-core-v1.3.3/{name}")
            info.type = tarfile.DIRTYPE
            bundle.addfile(info)
        for name, content in sorted(members.items()):
            info = tarfile.TarInfo(f"jarvis-core-v1.3.3/{name}")
            info.size = len(content)
            bundle.addfile(info, io.BytesIO(content))
    return (
        hashlib.sha256(archive.read_bytes()).hexdigest(),
        hashlib.sha256(manifest).hexdigest(),
    )


class ReleaseHelperTests(unittest.TestCase):
    def test_render_launcher_accepts_only_an_immutable_image_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            template = root / "launcher-template.sh"
            rendered = root / "launcher.sh"
            template_data = b"#!/bin/sh\nexec docker run IMAGE_ID_PLACEHOLDER\n"
            template.write_bytes(template_data)
            image_id = "sha256:" + "a" * 64

            rendered_hash = render_launcher(
                template,
                hashlib.sha256(template_data).hexdigest(),
                image_id,
                rendered,
            )

            self.assertIn(image_id.encode("ascii"), rendered.read_bytes())
            self.assertNotIn(b"IMAGE_ID_PLACEHOLDER", rendered.read_bytes())
            self.assertEqual(
                rendered_hash,
                hashlib.sha256(rendered.read_bytes()).hexdigest(),
            )
            with self.assertRaisesRegex(ReleaseError, "immutable"):
                render_launcher(
                    template,
                    hashlib.sha256(template_data).hexdigest(),
                    "jarvis-core:1.3.3",
                    root / "unsafe.sh",
                )

    def test_restore_launcher_replaces_any_active_state_with_verified_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            gate = root / "gate.sh"
            active = root / "active.sh"
            image_id = "sha256:" + "b" * 64
            gate_data = f"#!/bin/sh\nexec docker run {image_id}\n".encode("ascii")
            gate.write_bytes(gate_data)
            active.write_bytes(b"partially activated 1.3.3")
            gate_hash = hashlib.sha256(gate_data).hexdigest()

            restored = restore_launcher(gate, gate_hash, image_id, active)

            self.assertEqual(restored, active)
            self.assertEqual(active.read_bytes(), gate_data)
            verify_launcher(active, gate_hash, image_id)

    def test_verify_launcher_rejects_wrong_image_after_final_activation(self):
        with tempfile.TemporaryDirectory() as temporary:
            launcher = Path(temporary) / "active.sh"
            expected_image = "sha256:" + "c" * 64
            wrong_image = "sha256:" + "d" * 64
            data = f"#!/bin/sh\nexec docker run {wrong_image}\n".encode("ascii")
            launcher.write_bytes(data)

            with self.assertRaisesRegex(ReleaseError, "image ID"):
                verify_launcher(
                    launcher,
                    hashlib.sha256(data).hexdigest(),
                    expected_image,
                )

    def test_release_helper_cli_extracts_verified_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "release.tar.gz"
            archive_hash, manifest_hash = build_release_archive(
                archive, {"app/main.py": b"safe"}
            )
            destination = root / "destination"
            destination.mkdir()

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "release_helpers.py"),
                    "extract",
                    str(archive),
                    archive_hash,
                    manifest_hash,
                    str(destination),
                    "jarvis-core-v1.3.3",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertTrue(
                (destination / "jarvis-core-v1.3.3/app/main.py").is_file()
            )

    def test_activate_launcher_restores_rollback_after_failed_post_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "uploaded.sh"
            installed = root / "versioned.sh"
            active = root / "active.sh"
            rollback = root / "rollback.sh"
            new_data = b"#!/bin/sh\nexec new\n"
            old_data = b"#!/bin/sh\nexec old\n"
            source.write_bytes(new_data)
            active.write_bytes(old_data)
            rollback.write_bytes(old_data)

            with self.assertRaisesRegex(ReleaseError, "restored"):
                activate_launcher(
                    source,
                    hashlib.sha256(new_data).hexdigest(),
                    rollback,
                    hashlib.sha256(old_data).hexdigest(),
                    installed,
                    active,
                    post_replace_verifier=lambda _path: False,
                )

            self.assertEqual(active.read_bytes(), old_data)
            self.assertEqual(installed.read_bytes(), new_data)

    def test_verify_new_snapshot_rejects_success_without_new_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            backups = Path(temporary)
            old = backups / "20260721T120000Z"
            old.mkdir()

            with self.assertRaisesRegex(ReleaseError, "new snapshot"):
                verify_new_snapshot(
                    backups,
                    {old.name},
                    "/home/satellite/jarvis/vault-main",
                    "/home/satellite/jarvis/core-state-main-v1",
                )

    def test_verify_new_snapshot_rejects_bad_payload_checksum(self):
        with tempfile.TemporaryDirectory() as temporary:
            backups = Path(temporary)
            snapshot = backups / "20260721T130000Z"
            (snapshot / "vault").mkdir(parents=True)
            (snapshot / "state").mkdir()
            (snapshot / "vault/Nota.md").write_bytes(b"contenuto")
            (snapshot / "MANIFEST.txt").write_text(
                "created_utc=20260721T130000Z\n"
                "source_vault=/home/satellite/jarvis/vault-main\n"
                "source_state=/home/satellite/jarvis/core-state-main-v1\n"
                "previous_snapshot=none\n",
                encoding="utf-8",
            )
            (snapshot / "SHA256SUMS").write_text(
                f"{'0' * 64}  vault/Nota.md\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ReleaseError, "checksum"):
                verify_new_snapshot(
                    backups,
                    set(),
                    "/home/satellite/jarvis/vault-main",
                    "/home/satellite/jarvis/core-state-main-v1",
                )

    def test_verify_new_snapshot_accepts_complete_verified_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backups = root / "backups"
            live_vault = root / "vault-live"
            live_state = root / "state-live"
            backups.mkdir()
            live_vault.mkdir()
            live_state.mkdir()
            snapshot = backups / "20260721T140000Z"
            (snapshot / "vault").mkdir(parents=True)
            (snapshot / "state").mkdir()
            payload = b"contenuto verificato"
            (snapshot / "vault/Nota.md").write_bytes(payload)
            (live_vault / "Nota.md").write_bytes(payload)
            (snapshot / "MANIFEST.txt").write_text(
                "created_utc=20260721T140000Z\n"
                f"source_vault={live_vault}\n"
                f"source_state={live_state}\n"
                "previous_snapshot=none\n",
                encoding="utf-8",
            )
            (snapshot / "SHA256SUMS").write_text(
                f"{hashlib.sha256(payload).hexdigest()}  vault/Nota.md\n",
                encoding="utf-8",
            )

            verified = verify_new_snapshot(
                backups,
                set(),
                str(live_vault),
                str(live_state),
            )

            self.assertEqual(verified, snapshot)

    def test_verify_new_snapshot_rejects_incomplete_copy_of_live_trees(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backups = root / "backups"
            live_vault = root / "vault-live"
            live_state = root / "state-live"
            snapshot = backups / "20260721T150000Z"
            (snapshot / "vault").mkdir(parents=True)
            (snapshot / "state").mkdir()
            live_vault.mkdir()
            live_state.mkdir()
            (live_vault / "Nota non copiata.md").write_bytes(b"dato live")
            (snapshot / "MANIFEST.txt").write_text(
                "created_utc=20260721T150000Z\n"
                f"source_vault={live_vault}\n"
                f"source_state={live_state}\n"
                "previous_snapshot=none\n",
                encoding="utf-8",
            )
            (snapshot / "SHA256SUMS").write_text("", encoding="utf-8")

            with self.assertRaisesRegex(ReleaseError, "live"):
                verify_new_snapshot(
                    backups,
                    set(),
                    str(live_vault),
                    str(live_state),
                )

    def test_extract_verified_archive_rejects_traversal_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "release.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                info = tarfile.TarInfo("jarvis-core-v1.3.3/../../escape.txt")
                payload = b"escape"
                info.size = len(payload)
                bundle.addfile(info, io.BytesIO(payload))

            with self.assertRaises(ReleaseError):
                extract_verified_archive(
                    archive,
                    hashlib.sha256(archive.read_bytes()).hexdigest(),
                    "0" * 64,
                    root / "destination",
                    "jarvis-core-v1.3.3",
                )

            self.assertFalse((root / "escape.txt").exists())
            self.assertFalse((root / "destination").exists())

    def test_extract_verified_archive_rejects_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "release.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                link = tarfile.TarInfo("jarvis-core-v1.3.3/app/link.py")
                link.type = tarfile.SYMTYPE
                link.linkname = "../../outside.py"
                bundle.addfile(link)

            with self.assertRaisesRegex(ReleaseError, "regular files"):
                extract_verified_archive(
                    archive,
                    hashlib.sha256(archive.read_bytes()).hexdigest(),
                    "0" * 64,
                    root / "destination",
                    "jarvis-core-v1.3.3",
                )

    def test_extract_verified_archive_rejects_unmanifested_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "release.tar.gz"
            archive_hash, manifest_hash = build_release_archive(
                archive,
                {"app/main.py": b"safe"},
                {"sitecustomize.py": b"unexpected"},
            )

            with self.assertRaisesRegex(ReleaseError, "inventory"):
                extract_verified_archive(
                    archive,
                    archive_hash,
                    manifest_hash,
                    root / "destination",
                    "jarvis-core-v1.3.3",
                )

    def test_extract_verified_archive_rejects_unmanifested_directory_members(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "release.tar.gz"
            manifest = (
                f"{hashlib.sha256(b'safe').hexdigest()}  app/main.py\n"
            ).encode("utf-8")
            with tarfile.open(archive, "w:gz") as bundle:
                directory = tarfile.TarInfo("jarvis-core-v1.3.3/app")
                directory.type = tarfile.DIRTYPE
                bundle.addfile(directory)
                for name, content in {
                    "app/main.py": b"safe",
                    "SOURCE-SHA256SUMS": manifest,
                }.items():
                    info = tarfile.TarInfo(f"jarvis-core-v1.3.3/{name}")
                    info.size = len(content)
                    bundle.addfile(info, io.BytesIO(content))

            with self.assertRaisesRegex(ReleaseError, "inventory"):
                extract_verified_archive(
                    archive,
                    hashlib.sha256(archive.read_bytes()).hexdigest(),
                    hashlib.sha256(manifest).hexdigest(),
                    root,
                    "jarvis-core-v1.3.3",
                )
            self.assertFalse((root / "jarvis-core-v1.3.3").exists())

    def test_extract_verified_archive_rejects_file_prefix_collisions_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "release.tar.gz"
            files = {"app": b"file", "app/main.py": b"nested"}
            manifest = "".join(
                f"{hashlib.sha256(content).hexdigest()}  {name}\n"
                for name, content in sorted(files.items())
            ).encode("utf-8")
            with tarfile.open(archive, "w:gz") as bundle:
                for name, content in {
                    **files,
                    "SOURCE-SHA256SUMS": manifest,
                }.items():
                    info = tarfile.TarInfo(f"jarvis-core-v1.3.3/{name}")
                    info.size = len(content)
                    bundle.addfile(info, io.BytesIO(content))
            archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
            manifest_hash = hashlib.sha256(manifest).hexdigest()

            with self.assertRaisesRegex(ReleaseError, "prefix"):
                extract_verified_archive(
                    archive,
                    archive_hash,
                    manifest_hash,
                    root,
                    "jarvis-core-v1.3.3",
                )
            self.assertFalse((root / "jarvis-core-v1.3.3").exists())

    def test_extract_verified_archive_writes_only_verified_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "release.tar.gz"
            archive_hash, manifest_hash = build_release_archive(
                archive,
                {"app/main.py": b"safe", "README.md": b"release"},
            )
            destination = root / "destination"
            destination.mkdir()

            extracted = extract_verified_archive(
                archive,
                archive_hash,
                manifest_hash,
                destination,
                "jarvis-core-v1.3.3",
            )

            self.assertEqual(extracted, destination / "jarvis-core-v1.3.3")
            self.assertEqual((extracted / "app/main.py").read_bytes(), b"safe")
            self.assertEqual((extracted / "README.md").read_bytes(), b"release")
            self.assertTrue((extracted / "SOURCE-SHA256SUMS").is_file())


if __name__ == "__main__":
    unittest.main()
