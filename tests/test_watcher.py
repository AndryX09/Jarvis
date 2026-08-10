import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_ROOT))

import watcher as watcher_module
from watcher import (
    MAX_AUDIT_LINE_BYTES,
    MAX_RECENT_AUDIT_IDS,
    VaultWatcher,
    WatchEvent,
)


class VaultWatcherTests(unittest.TestCase):
    def test_poll_reports_markdown_file_modified_after_baseline(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            vault_root = Path(temporary_directory)
            note = vault_root / "Nota.md"
            note.write_text("prima", encoding="utf-8")

            watcher = VaultWatcher(vault_root)

            self.assertEqual(watcher.poll(), [])

            note.write_text("dopo", encoding="utf-8")
            self.assertEqual(watcher.poll(), [])
            [event] = watcher.poll()

            self.assertEqual(event.relative_path, "Nota.md")
            self.assertNotEqual(event.previous_sha256, event.sha256)

    def test_confirmed_event_is_appended_to_audit_log(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vault_root = root / "vault"
            state_root = root / "state"
            vault_root.mkdir()
            state_root.mkdir()

            note = vault_root / "Nota.md"
            note.write_text("prima", encoding="utf-8")

            watcher = VaultWatcher(vault_root, state_root=state_root)

            note.write_text("dopo", encoding="utf-8")
            self.assertEqual(watcher.poll(), [])
            [event] = watcher.poll()

            audit_path = state_root / "watcher-events.jsonl"
            records = [
                json.loads(line)
                for line in audit_path.read_text(encoding="utf-8").splitlines()
            ]

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["event_type"], "modified")
            self.assertEqual(records[0]["relative_path"], "Nota.md")
            self.assertEqual(
                records[0]["previous_sha256"], event.previous_sha256
            )
            self.assertEqual(records[0]["sha256"], event.sha256)
            self.assertEqual(records[0]["event_id"], event.event_id)
            self.assertEqual(len(event.event_id), 64)
            self.assertTrue(records[0]["timestamp_utc"].endswith("Z"))

    def test_large_valid_audit_remains_restartable(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vault_root = root / "vault"
            state_root = root / "state"
            vault_root.mkdir()
            state_root.mkdir()
            old_event = WatchEvent("created", "Old.md", None, "0" * 64, sequence=1)
            record_size = len(
                json.dumps({"event_id": "0" * 64, "sequence": 1}) + "\n"
            )
            repetitions = (10_000_000 // record_size) + 1
            audit_path = state_root / "watcher-events.jsonl"
            with audit_path.open("w", encoding="utf-8", newline="\n") as audit:
                audit.write(
                    json.dumps({"event_id": old_event.event_id, "sequence": 1}) + "\n"
                )
                for index in range(1, repetitions):
                    audit.write(
                        json.dumps(
                            {"event_id": f"{index:064x}", "sequence": index + 1}
                        )
                        + "\n"
                    )

            watcher = VaultWatcher(vault_root, state_root=state_root)
            size_before = audit_path.stat().st_size
            watcher._append_audit(old_event)

            self.assertLessEqual(len(watcher._audited_event_ids), MAX_RECENT_AUDIT_IDS)
            self.assertEqual(audit_path.stat().st_size, size_before)

    def test_audit_reader_bounds_each_read_before_materializing_a_line(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vault_root = root / "vault"
            state_root = root / "state"
            vault_root.mkdir()
            state_root.mkdir()
            (state_root / "watcher-events.jsonl").write_bytes(b"invalid\n")
            self_test = self

            class BoundedAudit:
                def __init__(self, descriptor):
                    self.descriptor = descriptor

                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    os.close(self.descriptor)

                def __iter__(self):
                    raise AssertionError("audit reader used unbounded text iteration")

                def readline(self, limit=-1):
                    self_test.assertEqual(limit, MAX_AUDIT_LINE_BYTES + 1)
                    return b"x" * limit

            def bounded_fdopen(descriptor, *_, **__):
                return BoundedAudit(descriptor)

            with mock.patch.object(
                watcher_module.os,
                "fdopen",
                side_effect=bounded_fdopen,
            ):
                with self.assertRaisesRegex(ValueError, "audit is invalid"):
                    VaultWatcher(vault_root, state_root=state_root)

    def test_repeated_transition_occurrences_have_distinct_audit_records(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vault_root = root / "vault"
            state_root = root / "state"
            vault_root.mkdir()
            state_root.mkdir()
            note = vault_root / "Nota.md"
            note.write_text("A", encoding="utf-8")
            watcher = VaultWatcher(vault_root, state_root=state_root)

            events = []
            for content in ("B", "A", "B"):
                note.write_text(content, encoding="utf-8")
                self.assertEqual(watcher.poll(), [])
                events.extend(watcher.poll())

            records = [
                json.loads(line)
                for line in (state_root / "watcher-events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(len(events), 3)
            self.assertEqual(len(records), 3)
            self.assertEqual(len({event.event_id for event in events}), 3)
            self.assertEqual(
                [record["event_id"] for record in records],
                [event.event_id for event in events],
            )

    def test_restart_detects_change_since_last_saved_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vault_root = root / "vault"
            state_root = root / "state"
            vault_root.mkdir()
            state_root.mkdir()

            note = vault_root / "Nota.md"
            note.write_text("prima", encoding="utf-8")
            VaultWatcher(vault_root, state_root=state_root)

            note.write_text("dopo", encoding="utf-8")
            restarted = VaultWatcher(vault_root, state_root=state_root)

            self.assertEqual(restarted.poll(), [])
            [event] = restarted.poll()

            self.assertEqual(event.relative_path, "Nota.md")
            self.assertNotEqual(event.previous_sha256, event.sha256)

    def test_poll_reports_created_markdown_file_after_debounce(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            vault_root = Path(temporary_directory)
            watcher = VaultWatcher(vault_root)

            note = vault_root / "Nuova.MD"
            note.write_text("contenuto", encoding="utf-8")

            self.assertEqual(watcher.poll(), [])
            [event] = watcher.poll()

            self.assertEqual(event.event_type, "created")
            self.assertEqual(event.relative_path, "Nuova.MD")
            self.assertIsNone(event.previous_sha256)
            self.assertIsNotNone(event.sha256)

    def test_poll_reports_deleted_markdown_file_after_debounce(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            vault_root = Path(temporary_directory)
            note = vault_root / "Eliminata.md"
            note.write_text("contenuto", encoding="utf-8")
            watcher = VaultWatcher(vault_root)

            note.unlink()

            self.assertEqual(watcher.poll(), [])
            [event] = watcher.poll()

            self.assertEqual(event.event_type, "deleted")
            self.assertEqual(event.relative_path, "Eliminata.md")
            self.assertIsNotNone(event.previous_sha256)
            self.assertIsNone(event.sha256)

    def test_deletion_without_preserved_previous_blob_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vault_root = root / "vault"
            state_root = root / "state"
            vault_root.mkdir()
            state_root.mkdir()
            note = vault_root / "Eliminata.md"
            note.write_text("contenuto", encoding="utf-8")
            watcher = VaultWatcher(vault_root, state_root=state_root)
            snapshot = json.loads(
                (state_root / "watcher-state.json").read_text(encoding="utf-8")
            )
            digest = snapshot["Eliminata.md"]
            (state_root / "watcher-originals" / f"{digest}.md").unlink()
            note.unlink()

            self.assertEqual(watcher.poll(), [])
            with self.assertRaisesRegex(ValueError, "unavailable"):
                watcher.poll()

            durable_snapshot = json.loads(
                (state_root / "watcher-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(durable_snapshot["Eliminata.md"], digest)

    def test_modified_note_preserves_previous_content_by_hash(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vault_root = root / "vault"
            state_root = root / "state"
            vault_root.mkdir()
            state_root.mkdir()

            note = vault_root / "Nota.md"
            note.write_text("prima", encoding="utf-8")
            watcher = VaultWatcher(vault_root, state_root=state_root)

            note.write_text("dopo", encoding="utf-8")
            self.assertEqual(watcher.poll(), [])
            [event] = watcher.poll()

            original = (
                state_root
                / "watcher-originals"
                / f"{event.previous_sha256}.md"
            )
            self.assertEqual(original.read_text(encoding="utf-8"), "prima")
            self.assertEqual(note.read_text(encoding="utf-8"), "dopo")

    def test_preserved_content_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vault_root = root / "vault"
            state_root = root / "state"
            originals_root = state_root / "watcher-originals"
            vault_root.mkdir()
            originals_root.mkdir(parents=True)
            content = b"private external content"
            digest = hashlib.sha256(content).hexdigest()
            (vault_root / "Nota.md").write_bytes(content)
            outside = root / "outside.md"
            outside.write_bytes(content)
            linked = originals_root / f"{digest}.md"
            try:
                linked.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"Symlinks are unavailable: {exc}")

            with self.assertRaisesRegex(ValueError, "invalid"):
                VaultWatcher(vault_root, state_root=state_root)

    def test_symlinked_markdown_file_outside_vault_is_ignored(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vault_root = root / "vault"
            state_root = root / "state"
            vault_root.mkdir()
            state_root.mkdir()
            outside = root / "outside.md"
            outside.write_text("outside before", encoding="utf-8")
            linked = vault_root / "Linked.md"
            try:
                linked.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"Symlinks are unavailable: {exc}")

            watcher = VaultWatcher(vault_root, state_root=state_root)
            outside.write_text("outside after", encoding="utf-8")

            self.assertEqual(watcher.poll(), [])
            self.assertEqual(watcher.poll(), [])

    def test_oversized_markdown_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            vault_root = Path(temporary_directory)
            (vault_root / "Large.md").write_bytes(b"x" * 1_000_001)

            with self.assertRaisesRegex(ValueError, "size limit"):
                VaultWatcher(vault_root)

    def test_corrupted_persisted_snapshot_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vault_root = root / "vault"
            state_root = root / "state"
            vault_root.mkdir()
            state_root.mkdir()
            (state_root / "watcher-state.json").write_text(
                json.dumps({"../outside.md": "not-a-sha256"}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "invalid"):
                VaultWatcher(vault_root, state_root=state_root)

    def test_corrupted_persisted_outbox_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vault_root = root / "vault"
            state_root = root / "state"
            vault_root.mkdir()
            state_root.mkdir()
            (state_root / "watcher-outbox.json").write_text(
                json.dumps(
                    [
                        {
                            "event_id": "not-the-real-id",
                            "event_type": "created",
                            "relative_path": "Idea.md",
                            "previous_sha256": None,
                            "sha256": "0" * 64,
                        }
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "outbox is invalid"):
                VaultWatcher(vault_root, state_root=state_root)

    def test_overlapping_vault_and_state_roots_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vault_root = root / "vault"
            vault_root.mkdir()
            state_inside_vault = vault_root / "state"
            state_inside_vault.mkdir()

            with self.assertRaisesRegex(ValueError, "must not overlap"):
                VaultWatcher(vault_root, state_root=state_inside_vault)

            state_root = root / "state"
            nested_vault = state_root / "vault"
            nested_vault.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "must not overlap"):
                VaultWatcher(nested_vault, state_root=state_root)

    def test_failed_consumer_is_retried_before_snapshot_advances(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vault_root = root / "vault"
            state_root = root / "state"
            vault_root.mkdir()
            state_root.mkdir()
            note = vault_root / "Nota.md"
            note.write_text("prima", encoding="utf-8")
            watcher = VaultWatcher(vault_root, state_root=state_root)
            note.write_text("dopo", encoding="utf-8")
            self.assertEqual(watcher.poll(), [])
            attempts = []

            def fail_once(event):
                attempts.append(event.event_id)
                raise OSError("temporary consumer failure")

            with self.assertRaises(OSError):
                watcher.poll(on_event=fail_once)

            note.write_text("prima", encoding="utf-8")
            restarted = VaultWatcher(vault_root, state_root=state_root)
            retried = restarted.poll(
                on_event=lambda event: attempts.append(event.event_id)
            )
            records = [
                json.loads(line)
                for line in (state_root / "watcher-events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]

            self.assertEqual(len(retried), 1)
            self.assertEqual(attempts, [retried[0].event_id, retried[0].event_id])
            self.assertEqual(len(records), 1)
            self.assertEqual(
                json.loads((state_root / "watcher-outbox.json").read_text()),
                [],
            )

    def test_replay_reverifies_all_blobs_before_callback_or_acknowledgement(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vault_root = root / "vault"
            state_root = root / "state"
            vault_root.mkdir()
            state_root.mkdir()
            note = vault_root / "Nota.md"
            note.write_text("prima", encoding="utf-8")
            watcher = VaultWatcher(vault_root, state_root=state_root)
            note.write_text("dopo", encoding="utf-8")
            self.assertEqual(watcher.poll(), [])

            with self.assertRaisesRegex(RuntimeError, "consumer failed"):
                watcher.poll(
                    on_event=lambda _: (_ for _ in ()).throw(
                        RuntimeError("consumer failed")
                    )
                )

            [queued] = json.loads(
                (state_root / "watcher-outbox.json").read_text(encoding="utf-8")
            )
            (state_root / "watcher-originals" / f"{queued['previous_sha256']}.md").unlink()
            delivered = []
            restarted = VaultWatcher(vault_root, state_root=state_root)

            with self.assertRaisesRegex(ValueError, "unavailable"):
                restarted.poll(on_event=lambda event: delivered.append(event.event_id))

            self.assertEqual(delivered, [])
            self.assertEqual(
                len(
                    json.loads(
                        (state_root / "watcher-outbox.json").read_text(
                            encoding="utf-8"
                        )
                    )
                ),
                1,
            )
            snapshot = json.loads(
                (state_root / "watcher-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(snapshot["Nota.md"], queued["previous_sha256"])

    def test_failed_outbox_persistence_never_exposes_memory_only_event(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vault_root = root / "vault"
            state_root = root / "state"
            vault_root.mkdir()
            state_root.mkdir()
            note = vault_root / "Nota.md"
            note.write_text("prima", encoding="utf-8")
            watcher = VaultWatcher(vault_root, state_root=state_root)
            note.write_text("dopo", encoding="utf-8")
            self.assertEqual(watcher.poll(), [])
            delivered = []

            with mock.patch.object(
                watcher,
                "_save_outbox",
                side_effect=OSError("simulated disk failure"),
            ):
                with self.assertRaises(OSError):
                    watcher.poll(on_event=lambda event: delivered.append(event.event_id))
            self.assertEqual(delivered, [])

            def require_durable_outbox(event):
                records = json.loads(
                    (state_root / "watcher-outbox.json").read_text(encoding="utf-8")
                )
                self.assertIn(event.event_id, [record["event_id"] for record in records])
                delivered.append(event.event_id)

            events = watcher.poll(on_event=require_durable_outbox)
            self.assertEqual(len(events), 1)
            self.assertEqual(delivered, [events[0].event_id])

    def test_failed_snapshot_persistence_leaves_event_in_durable_outbox(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vault_root = root / "vault"
            state_root = root / "state"
            vault_root.mkdir()
            state_root.mkdir()
            note = vault_root / "Nota.md"
            note.write_text("prima", encoding="utf-8")
            watcher = VaultWatcher(vault_root, state_root=state_root)
            note.write_text("dopo", encoding="utf-8")
            self.assertEqual(watcher.poll(), [])
            delivered = []

            with mock.patch.object(
                watcher,
                "_save_snapshot",
                side_effect=OSError("simulated snapshot failure"),
            ):
                with self.assertRaises(OSError):
                    watcher.poll(on_event=lambda event: delivered.append(event.event_id))

            records = json.loads(
                (state_root / "watcher-outbox.json").read_text(encoding="utf-8")
            )
            self.assertEqual(delivered, [records[0]["event_id"]])

    def test_ancestor_symlink_swap_aborts_scan_before_external_read(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vault_root = root / "vault"
            state_root = root / "state"
            folder = vault_root / "Folder"
            external = root / "external"
            folder.mkdir(parents=True)
            external.mkdir()
            state_root.mkdir()
            note = folder / "Nota.md"
            note.write_text("interno", encoding="utf-8")
            (external / "Nota.md").write_text("segreto esterno", encoding="utf-8")
            watcher = VaultWatcher(vault_root, state_root=state_root)
            note.write_text("interno modificato", encoding="utf-8")
            original_is_file = Path.is_file
            swapped = False

            def swap_parent_after_type_check(path):
                nonlocal swapped
                result = original_is_file(path)
                if path == note and result and not swapped:
                    swapped = True
                    folder.rename(vault_root / "Folder-old")
                    try:
                        os.symlink(external, folder, target_is_directory=True)
                    except (OSError, NotImplementedError):
                        self.skipTest("directory symbolic links are unavailable")
                return result

            with mock.patch.object(Path, "is_file", swap_parent_after_type_check):
                with self.assertRaisesRegex(ValueError, "path is invalid"):
                    watcher.poll()

            external_digest = hashlib.sha256(b"segreto esterno").hexdigest()
            self.assertFalse(
                (state_root / "watcher-originals" / f"{external_digest}.md").exists()
            )

if __name__ == "__main__":
    unittest.main()