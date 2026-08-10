import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import vault_core as vault_core_module
from app.vault_core import (
    JarvisError,
    append_to_note_in_vault,
    capture_material,
    create_inbox_note,
    create_note_in_vault,
    ingestion_status,
    list_captures,
    list_notes_in_vault,
    list_note_versions,
    list_tasks_in_vault,
    move_note_in_vault,
    read_capture,
    read_pending_captures,
    read_ingestion_policy,
    read_note_from_vault,
    read_note_version,
    recent_activity,
    restore_note_version,
    search_vault,
    update_note_in_vault,
    update_capture_status,
    vault_status,
    watcher_status,
)


class JarvisCoreTests(unittest.TestCase):
    def setUp(self):
        self.vault_temp = tempfile.TemporaryDirectory()
        self.state_temp = tempfile.TemporaryDirectory()
        self.root = Path(self.vault_temp.name).resolve()
        self.state = Path(self.state_temp.name).resolve()
        (self.root / "Ricerca di prova.md").write_text(
            "# Ricerca\nLa parola speciale e lucciola-blu.\n- [ ] Controllare Jarvis\n",
            encoding="utf-8",
        )
        (self.root / "Progetti").mkdir()
        (self.root / "Progetti" / "Decisioni.md").write_text(
            "Decisione confermata: testare in sicurezza.\n", encoding="utf-8"
        )
        (self.root / ".obsidian").mkdir()
        (self.root / ".obsidian" / "private.md").write_text(
            "lucciola-blu\n- [ ] Privato\n", encoding="utf-8"
        )

    def tearDown(self):
        self.vault_temp.cleanup()
        self.state_temp.cleanup()

    def test_search_and_read_include_revision_hash(self):
        result = search_vault(self.root, "LUCCIOLA-BLU")
        self.assertEqual([item["path"] for item in result["matches"]], ["Ricerca di prova.md"])
        note = read_note_from_vault(self.root, "Ricerca di prova.md")
        self.assertEqual(note["sha256"], hashlib.sha256(note["content"].encode()).hexdigest())

    def test_hidden_paths_and_traversal_are_rejected(self):
        for path in (".obsidian/private.md", "../outside.md", "/tmp/outside.md"):
            with self.subTest(path=path), self.assertRaises(JarvisError):
                read_note_from_vault(self.root, path)

    def test_list_notes_and_tasks_skip_hidden_content(self):
        notes = list_notes_in_vault(self.root)
        self.assertEqual(
            [item["path"] for item in notes["notes"]],
            ["Ricerca di prova.md", "Progetti/Decisioni.md"],
        )
        tasks = list_tasks_in_vault(self.root)
        self.assertEqual(len(tasks["tasks"]), 1)
        self.assertEqual(tasks["tasks"][0]["task"], "Controllare Jarvis")

    def test_create_note_never_overwrites(self):
        created = create_note_in_vault(
            self.root, self.state, "Nuove/Idea.md", "# Idea\n"
        )
        self.assertTrue(created["created"])
        self.assertEqual((self.root / "Nuove" / "Idea.md").read_text(), "# Idea\n")
        with self.assertRaises(JarvisError):
            create_note_in_vault(
                self.root, self.state, "Nuove/Idea.md", "sovrascrittura"
            )

    def test_inbox_note_is_limited_to_ai_inbox(self):
        result = create_inbox_note(self.root, self.state, "Una nuova idea", "Testo")
        self.assertTrue(result["path"].startswith("AI Inbox/"))
        self.assertTrue((self.root / result["path"]).is_file())

    def test_append_requires_current_hash_and_creates_backup(self):
        original = read_note_from_vault(self.root, "Ricerca di prova.md")
        result = append_to_note_in_vault(
            self.root,
            self.state,
            "Ricerca di prova.md",
            "\nAggiunta controllata.\n",
            original["sha256"],
        )
        self.assertIn("Aggiunta controllata", (self.root / "Ricerca di prova.md").read_text())
        self.assertTrue((self.state / result["backup_path"]).is_file())
        with self.assertRaises(JarvisError):
            append_to_note_in_vault(
                self.root,
                self.state,
                "Ricerca di prova.md",
                "stale",
                original["sha256"],
            )

    def test_update_preserves_previous_content_and_audits_without_content(self):
        original = read_note_from_vault(self.root, "Progetti/Decisioni.md")
        result = update_note_in_vault(
            self.root,
            self.state,
            "Progetti/Decisioni.md",
            "# Nuova versione\n",
            original["sha256"],
        )
        backup = self.state / result["backup_path"]
        self.assertIn("Decisione confermata", backup.read_text())
        events = recent_activity(self.state)["events"]
        self.assertEqual(events[0]["action"], "update_note")
        self.assertNotIn("content", events[0])

    def test_list_and_read_versions_return_hash_and_content(self):
        original = read_note_from_vault(self.root, "Ricerca di prova.md")
        result = append_to_note_in_vault(
            self.root,
            self.state,
            "Ricerca di prova.md",
            "\nVersione nuova.\n",
            original["sha256"],
        )
        version_id = Path(result["backup_path"]).parts[1]

        versions = list_note_versions(self.state, "Ricerca di prova.md")
        self.assertEqual(versions["versions"][0]["version_id"], version_id)
        self.assertEqual(versions["versions"][0]["sha256"], original["sha256"])

        saved = read_note_version(self.state, "Ricerca di prova.md", version_id)
        self.assertEqual(saved["content"], original["content"])
        self.assertEqual(saved["sha256"], original["sha256"])

    def test_restore_requires_both_hashes_and_preserves_current_version(self):
        original = read_note_from_vault(self.root, "Ricerca di prova.md")
        appended = append_to_note_in_vault(
            self.root,
            self.state,
            "Ricerca di prova.md",
            "\nVersione da annullare.\n",
            original["sha256"],
        )
        version_id = Path(appended["backup_path"]).parts[1]
        current = read_note_from_vault(self.root, "Ricerca di prova.md")
        saved = read_note_version(self.state, "Ricerca di prova.md", version_id)

        with self.assertRaises(JarvisError):
            restore_note_version(
                self.root,
                self.state,
                "Ricerca di prova.md",
                version_id,
                current["sha256"],
                "0" * 64,
            )
        self.assertEqual(
            read_note_from_vault(self.root, "Ricerca di prova.md")["sha256"],
            current["sha256"],
        )

        restored = restore_note_version(
            self.root,
            self.state,
            "Ricerca di prova.md",
            version_id,
            current["sha256"],
            saved["sha256"],
        )

        self.assertEqual(restored["sha256"], original["sha256"])
        self.assertEqual(
            read_note_from_vault(self.root, "Ricerca di prova.md")["content"],
            original["content"],
        )
        self.assertIn(
            "Versione da annullare",
            (self.state / restored["backup_path"]).read_text(encoding="utf-8"),
        )
        self.assertEqual(recent_activity(self.state)["events"][0]["action"], "restore_version")

        with self.assertRaises(JarvisError):
            restore_note_version(
                self.root,
                self.state,
                "Ricerca di prova.md",
                version_id,
                current["sha256"],
                saved["sha256"],
            )

    def test_version_identifiers_and_paths_reject_traversal(self):
        with self.assertRaises(JarvisError):
            list_note_versions(self.state, "../outside.md")
        with self.assertRaises(JarvisError):
            read_note_version(self.state, "Ricerca di prova.md", "../../outside")

    @unittest.skipIf(os.name == "nt", "POSIX file modes are verified on Ubuntu")
    def test_update_preserves_note_permissions(self):
        note = self.root / "Permissions.md"
        note.write_text("before", encoding="utf-8")
        os.chmod(note, 0o640)
        original = read_note_from_vault(self.root, "Permissions.md")

        update_note_in_vault(
            self.root,
            self.state,
            "Permissions.md",
            "after",
            original["sha256"],
        )

        self.assertEqual(note.stat().st_mode & 0o777, 0o640)

    def test_move_refuses_overwrite_and_preserves_backup(self):
        source = read_note_from_vault(self.root, "Progetti/Decisioni.md")
        result = move_note_in_vault(
            self.root,
            self.state,
            "Progetti/Decisioni.md",
            "Archivio/Decisioni.md",
            source["sha256"],
        )
        self.assertFalse((self.root / "Progetti" / "Decisioni.md").exists())
        self.assertTrue((self.root / "Archivio" / "Decisioni.md").exists())
        self.assertTrue((self.state / result["backup_path"]).exists())
        with self.assertRaises(JarvisError):
            move_note_in_vault(
                self.root,
                self.state,
                "Archivio/Decisioni.md",
                "Ricerca di prova.md",
                source["sha256"],
            )

    def test_wrong_extension_and_windows_separator_are_rejected(self):
        for path in ("nota.txt", "Cartella\\nota.md"):
            with self.subTest(path=path), self.assertRaises(JarvisError):
                create_note_in_vault(self.root, self.state, path, "test")

    def test_status_explicitly_reports_security_and_policy_capabilities(self):
        status = vault_status(self.root, self.state)
        self.assertEqual(status["version"], "1.4.0")
        self.assertEqual(
            status["session_mode"], "multi-session-with-shared-mutation-lock"
        )
        self.assertTrue(status["concurrent_reads_available"])
        self.assertTrue(status["concurrent_mutations_serialized"])
        self.assertTrue(status["ingestion_available"])
        self.assertTrue(status["raw_material_is_preserved"])
        self.assertFalse(status["delete_tool_available"])
        self.assertFalse(status["network_required"])
        self.assertTrue(status["capture_status_transition_policy_enforced"])
        self.assertEqual(
            status["policy_paths"]["organization"],
            "Sistema — Gestione automatica delle note.md",
        )
        self.assertEqual(
            status["policy_paths"]["ingestion"],
            "Sistema — Acquisizione e triage.md",
        )

    def test_watcher_status_does_not_follow_symlink_swapped_before_read(self):
        status_path = self.state / "watcher-service-status.json"
        status_path.write_text(
            json.dumps(
                {
                    "service": "stopped",
                    "rule_version": "watcher-policy-v1",
                    "last_poll_utc": "",
                    "events_processed": 1,
                    "captures_created": 0,
                    "review_required": 0,
                    "ignored": 0,
                    "errors": 0,
                }
            ),
            encoding="utf-8",
        )
        external = self.root / "external-status.json"
        external.write_text(
            json.dumps(
                {
                    "service": "EXTERNAL_SECRET",
                    "rule_version": "external",
                    "last_poll_utc": "",
                    "events_processed": 999,
                    "captures_created": 999,
                    "review_required": 999,
                    "ignored": 999,
                    "errors": 999,
                }
            ),
            encoding="utf-8",
        )
        original_read_text = Path.read_text

        def swap_before_read(path, *args, **kwargs):
            if path == status_path:
                status_path.unlink()
                try:
                    os.symlink(external, status_path)
                except (OSError, NotImplementedError):
                    self.skipTest("symbolic links are unavailable")
            return original_read_text(path, *args, **kwargs)

        with mock.patch.object(Path, "read_text", swap_before_read):
            result = watcher_status(self.state)

        self.assertNotEqual(result["service"], "EXTERNAL_SECRET")
        self.assertNotEqual(result["events_processed"], 999)

    def test_ingestion_policy_reads_dedicated_policy_from_vault(self):
        organization_path = self.root / "Sistema — Gestione automatica delle note.md"
        organization_path.write_text("# Organizzazione\n", encoding="utf-8")
        ingestion_path = self.root / "Sistema — Acquisizione e triage.md"
        ingestion_path.write_text(
            "# Acquisizione e triage\n\nConservare gli originali.\n",
            encoding="utf-8",
        )

        policy = read_ingestion_policy(self.root)

        self.assertEqual(
            policy["policy_path"], "Sistema — Acquisizione e triage.md"
        )
        self.assertIn("Conservare gli originali", policy["content"])
        self.assertNotIn("# Organizzazione", policy["content"])
        self.assertEqual(
            policy["sha256"], hashlib.sha256(policy["content"].encode()).hexdigest()
        )

    def test_ingestion_policy_never_falls_back_to_organization_policy(self):
        organization_path = self.root / "Sistema — Gestione automatica delle note.md"
        organization_path.write_text("# Organizzazione\n", encoding="utf-8")

        with self.assertRaises(JarvisError):
            read_ingestion_policy(self.root)

    def test_organization_policy_reads_dedicated_policy_from_vault(self):
        policy_path = self.root / "Sistema — Gestione automatica delle note.md"
        policy_path.write_text(
            "# Organizzazione\n\nNon inventare informazioni.\n", encoding="utf-8"
        )
        reader = getattr(vault_core_module, "read_organization_policy", None)

        self.assertTrue(callable(reader), "read_organization_policy must be available")
        policy = reader(self.root)

        self.assertEqual(
            policy["policy_path"], "Sistema — Gestione automatica delle note.md"
        )
        self.assertIn("Non inventare informazioni", policy["content"])
        self.assertEqual(
            policy["sha256"], hashlib.sha256(policy["content"].encode()).hexdigest()
        )

    def test_capture_preserves_raw_material_and_deduplicates_exact_content(self):
        first = capture_material(
            self.state,
            "Idea Keep",
            "Testo originale senza modifiche.",
            "google-keep",
            "keep-id-123",
            ["video", "idea"],
        )
        duplicate = capture_material(
            self.state,
            "Titolo diverso",
            "Testo originale senza modifiche.",
            "google-keep",
            "keep-id-123",
        )
        distinct_source = capture_material(
            self.state,
            "Stesso testo, altra nota",
            "Testo originale senza modifiche.",
            "google-keep",
            "keep-id-456",
        )

        self.assertTrue(first["created"])
        self.assertFalse(first["duplicate"])
        self.assertFalse(duplicate["created"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["capture_id"], first["capture_id"])
        self.assertTrue(distinct_source["created"])
        self.assertEqual(len(list_captures(self.state)["captures"]), 2)
        stored = read_capture(self.state, first["capture_id"])
        self.assertEqual(stored["content"], "Testo originale senza modifiche.")
        self.assertEqual(stored["status"], "pending")

    def test_capture_lists_metadata_without_raw_content(self):
        captured = capture_material(self.state, "Titolo", "Contenuto privato")

        listed = list_captures(self.state, "pending")

        self.assertEqual(listed["captures"][0]["capture_id"], captured["capture_id"])
        self.assertNotIn("content", listed["captures"][0])
        event = recent_activity(self.state)["events"][0]
        self.assertEqual(event["action"], "capture_material")
        self.assertNotIn("content", event)

    def test_pending_batch_returns_bounded_raw_content_without_mutation(self):
        first = capture_material(self.state, "Uno", "Contenuto uno")
        second = capture_material(self.state, "Due", "Contenuto due")

        result = read_pending_captures(self.state, 2)

        self.assertEqual(result["capture_count"], 2)
        self.assertEqual(
            {item["content"] for item in result["captures"]},
            {"Contenuto uno", "Contenuto due"},
        )
        self.assertEqual(read_capture(self.state, first["capture_id"])["status"], "pending")
        self.assertEqual(read_capture(self.state, second["capture_id"])["status"], "pending")

    def test_pending_batch_enforces_small_result_limit(self):
        capture_material(self.state, "Uno", "Contenuto uno")
        with self.assertRaises(JarvisError):
            read_pending_captures(self.state, 21)

    def test_ready_status_separates_triaged_material_from_pending(self):
        captured = capture_material(self.state, "Idea", "Materiale utile")
        current = read_capture(self.state, captured["capture_id"])

        ready = update_capture_status(
            self.root,
            self.state,
            captured["capture_id"],
            "ready",
            current["record_sha256"],
            [],
            "Triage completato: materiale utile.",
        )

        self.assertEqual(ready["status"], "ready")
        self.assertEqual(list_captures(self.state, "pending")["captures"], [])
        self.assertEqual(
            list_captures(self.state, "ready")["captures"][0]["capture_id"],
            captured["capture_id"],
        )
        self.assertEqual(read_pending_captures(self.state)["captures"], [])

    def test_processed_capture_requires_fresh_hash_and_existing_output_note(self):
        captured = capture_material(self.state, "Idea", "Materiale grezzo")
        create_note_in_vault(
            self.root, self.state, "Progetti/Idea elaborata.md", "# Idea elaborata\n"
        )
        current = read_capture(self.state, captured["capture_id"])

        with self.assertRaises(JarvisError):
            update_capture_status(
                self.root,
                self.state,
                captured["capture_id"],
                "processed",
                "0" * 64,
                ["Progetti/Idea elaborata.md"],
                "Tentativo con hash non aggiornato.",
            )

        ready = update_capture_status(
            self.root,
            self.state,
            captured["capture_id"],
            "ready",
            current["record_sha256"],
            [],
            "Materiale approvato per l'organizzazione.",
        )
        processed = update_capture_status(
            self.root,
            self.state,
            captured["capture_id"],
            "processed",
            ready["record_sha256"],
            ["Progetti/Idea elaborata.md"],
            "Trasformata seguendo il template.",
        )

        self.assertEqual(processed["status"], "processed")
        self.assertEqual(processed["output_paths"], ["Progetti/Idea elaborata.md"])
        self.assertEqual(
            read_capture(self.state, captured["capture_id"])["content"],
            "Materiale grezzo",
        )
        self.assertEqual(len(list_captures(self.state, "pending")["captures"]), 0)
        self.assertEqual(len(list_captures(self.state, "processed")["captures"]), 1)

    def test_pending_capture_cannot_be_processed_directly(self):
        captured = capture_material(self.state, "Idea", "Materiale grezzo")
        create_note_in_vault(
            self.root, self.state, "Progetti/Output.md", "# Output\n"
        )
        current = read_capture(self.state, captured["capture_id"])

        with self.assertRaisesRegex(JarvisError, "pending -> processed"):
            update_capture_status(
                self.root,
                self.state,
                captured["capture_id"],
                "processed",
                current["record_sha256"],
                ["Progetti/Output.md"],
                "Organizzazione non ancora autorizzata.",
            )

    def test_capture_status_rejects_transitions_outside_policy_matrix(self):
        capture_number = 0
        output_number = 0

        def capture_in_status(initial_status):
            nonlocal capture_number, output_number
            capture_number += 1
            captured = capture_material(
                self.state,
                f"Cattura {initial_status} {capture_number}",
                f"Materiale di prova {capture_number}",
            )
            current = read_capture(self.state, captured["capture_id"])
            if initial_status == "pending":
                return current
            first = update_capture_status(
                self.root,
                self.state,
                captured["capture_id"],
                "ready" if initial_status in {"ready", "processed"} else "skipped",
                current["record_sha256"],
                [],
                "Preparazione dello stato di prova.",
            )
            if initial_status != "processed":
                return first
            output_number += 1
            output_path = f"Progetti/Output matrice {output_number}.md"
            create_note_in_vault(self.root, self.state, output_path, "# Output\n")
            return update_capture_status(
                self.root,
                self.state,
                captured["capture_id"],
                "processed",
                first["record_sha256"],
                [output_path],
                "Output di prova creato.",
            )

        invalid_transitions = (
            ("pending", "pending"),
            ("ready", "pending"),
            ("ready", "ready"),
            ("skipped", "skipped"),
            ("skipped", "processed"),
            ("processed", "pending"),
            ("processed", "ready"),
            ("processed", "skipped"),
            ("processed", "processed"),
        )
        for before_status, after_status in invalid_transitions:
            with self.subTest(before=before_status, after=after_status):
                current = capture_in_status(before_status)
                output_paths = []
                if after_status == "processed":
                    output_number += 1
                    output_path = f"Progetti/Output transizione {output_number}.md"
                    create_note_in_vault(
                        self.root, self.state, output_path, "# Output transizione\n"
                    )
                    output_paths = [output_path]
                with self.assertRaisesRegex(
                    JarvisError, f"{before_status} -> {after_status}"
                ):
                    update_capture_status(
                        self.root,
                        self.state,
                        current["capture_id"],
                        after_status,
                        current["record_sha256"],
                        output_paths,
                        "Transizione non consentita.",
                    )

    def test_capture_status_refuses_missing_output_and_can_be_reopened(self):
        captured = capture_material(self.state, "Idea", "Materiale")
        current = read_capture(self.state, captured["capture_id"])
        with self.assertRaises(JarvisError):
            update_capture_status(
                self.root,
                self.state,
                captured["capture_id"],
                "processed",
                current["record_sha256"],
                ["Non esiste.md"],
                "Output dichiarato ma non esistente.",
            )

        skipped = update_capture_status(
            self.root,
            self.state,
            captured["capture_id"],
            "skipped",
            current["record_sha256"],
            [],
            "Non contiene informazioni di progetto.",
        )
        reopened = update_capture_status(
            self.root,
            self.state,
            captured["capture_id"],
            "pending",
            skipped["record_sha256"],
            [],
            "Rivalutazione richiesta dall'utente.",
        )
        self.assertEqual(reopened["status"], "pending")

    def test_ready_capture_cannot_process_a_nonexistent_output_note(self):
        captured = capture_material(self.state, "Idea pronta", "Materiale utile")
        pending = read_capture(self.state, captured["capture_id"])
        ready = update_capture_status(
            self.root,
            self.state,
            captured["capture_id"],
            "ready",
            pending["record_sha256"],
            [],
            "Materiale pronto per l'organizzazione.",
        )

        with self.assertRaises(JarvisError):
            update_capture_status(
                self.root,
                self.state,
                captured["capture_id"],
                "processed",
                ready["record_sha256"],
                ["Output inesistente.md"],
                "Output dichiarato ma non creato.",
            )
        unchanged = read_capture(self.state, captured["capture_id"])
        self.assertEqual(unchanged["status"], "ready")
        self.assertEqual(unchanged["record_sha256"], ready["record_sha256"])

    def test_capture_status_requires_non_empty_summary(self):
        captured = capture_material(self.state, "Idea", "Materiale")
        current = read_capture(self.state, captured["capture_id"])

        with self.assertRaisesRegex(JarvisError, "summary"):
            update_capture_status(
                self.root,
                self.state,
                captured["capture_id"],
                "ready",
                current["record_sha256"],
                [],
                "   \n",
            )

        with self.assertRaisesRegex(JarvisError, "2000"):
            update_capture_status(
                self.root,
                self.state,
                captured["capture_id"],
                "ready",
                current["record_sha256"],
                [],
                "x" * 2001,
            )

        with self.assertRaisesRegex(JarvisError, "2000"):
            update_capture_status(
                self.root,
                self.state,
                captured["capture_id"],
                "ready",
                current["record_sha256"],
                [],
                " " * 2001 + "Motivo",
            )

    def test_capture_status_accepts_remaining_allowed_transitions(self):
        first = capture_material(self.state, "Prima", "Materiale uno")
        first_pending = read_capture(self.state, first["capture_id"])
        first_ready = update_capture_status(
            self.root, self.state, first["capture_id"], "ready",
            first_pending["record_sha256"], [], "Materiale utile."
        )
        first_skipped = update_capture_status(
            self.root, self.state, first["capture_id"], "skipped",
            first_ready["record_sha256"], [], "Esclusione confermata."
        )
        self.assertEqual(first_skipped["status"], "skipped")

        second = capture_material(self.state, "Seconda", "Materiale due")
        second_pending = read_capture(self.state, second["capture_id"])
        second_skipped = update_capture_status(
            self.root, self.state, second["capture_id"], "skipped",
            second_pending["record_sha256"], [], "Esclusione iniziale."
        )
        second_ready = update_capture_status(
            self.root, self.state, second["capture_id"], "ready",
            second_skipped["record_sha256"], [], "Rivalutazione esplicita."
        )
        self.assertEqual(second_ready["status"], "ready")

    def test_capture_output_paths_are_bounded_and_processed_only(self):
        captured = capture_material(self.state, "Idea", "Materiale")
        current = read_capture(self.state, captured["capture_id"])

        with self.assertRaisesRegex(JarvisError, "at most 20"):
            update_capture_status(
                self.root,
                self.state,
                captured["capture_id"],
                "processed",
                current["record_sha256"],
                [f"Output-{index}.md" for index in range(21)],
                "Troppi output.",
            )

        create_note_in_vault(self.root, self.state, "Output.md", "# Output\n")
        with self.assertRaisesRegex(JarvisError, "Only processed"):
            update_capture_status(
                self.root,
                self.state,
                captured["capture_id"],
                "ready",
                current["record_sha256"],
                ["Output.md"],
                "Output non consentito durante il triage.",
            )

    def test_ingestion_status_counts_captures_and_never_offers_deletion(self):
        first = capture_material(self.state, "Uno", "Materiale uno")
        capture_material(self.state, "Due", "Materiale due")
        current = read_capture(self.state, first["capture_id"])
        update_capture_status(
            self.root,
            self.state,
            first["capture_id"],
            "ready",
            current["record_sha256"],
            [],
            "Triage completato.",
        )

        result = ingestion_status(self.root, self.state)

        self.assertEqual(result["captures"]["total"], 2)
        self.assertEqual(result["captures"]["pending"], 1)
        self.assertEqual(result["captures"]["ready"], 1)
        self.assertFalse(result["automatic_deletion_available"])
        self.assertTrue(result["raw_material_is_preserved"])


if __name__ == "__main__":
    unittest.main()
