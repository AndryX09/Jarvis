import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_ROOT))

from watcher_service import WatcherService
from vault_core import watcher_status


class WatcherServiceTests(unittest.TestCase):
    def test_overlapping_roots_are_rejected_before_service_state_is_written(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            vault_root = Path(temporary_directory)
            state_root = vault_root / "state"
            state_root.mkdir()

            with self.assertRaisesRegex(ValueError, "must not overlap"):
                WatcherService(vault_root, state_root)

            self.assertEqual(list(state_root.iterdir()), [])

    def test_pm2_config_uses_separate_python_interpreter_and_script_paths(self):
        ecosystem = (
            Path(__file__).resolve().parents[1] / "ecosystem.config.js"
        ).read_text(encoding="utf-8")

        self.assertEqual(ecosystem.count('interpreter: ".venv/bin/python3"'), 2)
        self.assertIn('script: "app/server.py"', ecosystem)
        self.assertIn('script: "app/watcher_service.py"', ecosystem)
        self.assertNotIn('script: ".venv/bin/python3 ', ecosystem)

    def test_stale_running_status_is_not_reported_as_live(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory)
            (state_root / "watcher-service-status.json").write_text(
                json.dumps(
                    {
                        "service": "running",
                        "rule_version": "deterministic-v1",
                        "last_poll_utc": "2000-01-01T00:00:00Z",
                        "events_processed": 4,
                        "captures_created": 1,
                        "review_required": 2,
                        "ignored": 1,
                        "errors": 0,
                    }
                ),
                encoding="utf-8",
            )

            status = watcher_status(state_root)

            self.assertEqual(status["service"], "stale")
            self.assertEqual(status["events_processed"], 4)

    def test_cycles_queue_capture_and_publish_content_free_status(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vault_root = root / "vault"
            state_root = root / "state"
            inbox = vault_root / "AI Inbox"
            inbox.mkdir(parents=True)
            state_root.mkdir()
            service = WatcherService(vault_root, state_root)

            note = inbox / "Idea.md"
            note.write_text("contenuto privato", encoding="utf-8")

            self.assertEqual(service.run_cycle(), [])
            [result] = service.run_cycle()

            status_path = state_root / "watcher-service-status.json"
            status_text = status_path.read_text(encoding="utf-8")
            status = json.loads(status_text)

            self.assertEqual(result.action, "queue_capture")
            self.assertEqual(status["service"], "running")
            self.assertEqual(status["events_processed"], 1)
            self.assertEqual(status["captures_created"], 1)
            self.assertEqual(status["review_required"], 0)
            self.assertEqual(status["errors"], 0)
            self.assertNotIn("Idea.md", status_text)
            self.assertNotIn("contenuto privato", status_text)

            service.close()
            WatcherService(vault_root, state_root)
            restarted_status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(restarted_status["events_processed"], 1)
            self.assertEqual(restarted_status["captures_created"], 1)

    def test_failed_capture_is_retried_before_event_acknowledgement(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vault_root = root / "vault"
            state_root = root / "state"
            inbox = vault_root / "AI Inbox"
            inbox.mkdir(parents=True)
            state_root.mkdir()
            service = WatcherService(vault_root, state_root)
            note = inbox / "Idea.md"
            note.write_text("retry me", encoding="utf-8")
            self.assertEqual(service.run_cycle(), [])
            capture_blocker = state_root / "captures"
            capture_blocker.write_text("not a directory", encoding="utf-8")

            with self.assertLogs("watcher_service", level="ERROR"):
                self.assertEqual(service.run_cycle(), [])
            capture_blocker.unlink()
            note.unlink()
            service.close()
            service = WatcherService(vault_root, state_root)
            retried = service.run_cycle()

            self.assertEqual(len(retried), 1)
            self.assertEqual(retried[0].action, "queue_capture")
            self.assertTrue(retried[0].capture_created)

    def test_permanently_invalid_capture_does_not_starve_later_events(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vault_root = root / "vault"
            state_root = root / "state"
            inbox = vault_root / "AI Inbox"
            inbox.mkdir(parents=True)
            state_root.mkdir()
            service = WatcherService(vault_root, state_root)
            (inbox / "A-empty.md").write_text("   \n", encoding="utf-8")
            (inbox / "B-valid.md").write_text("valid", encoding="utf-8")

            self.assertEqual(service.run_cycle(), [])
            results = service.run_cycle()

            self.assertEqual(
                sorted(result.action for result in results),
                ["queue_capture", "review_required"],
            )
            self.assertEqual(
                sum(result.capture_created is True for result in results),
                1,
            )

    @unittest.skipIf(os.name == "nt", "fcntl watcher lock is Linux-only")
    def test_second_service_for_same_state_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vault_root = root / "vault"
            state_root = root / "state"
            vault_root.mkdir()
            state_root.mkdir()
            first = WatcherService(vault_root, state_root)
            try:
                with self.assertRaisesRegex(ValueError, "already running"):
                    WatcherService(vault_root, state_root)
            finally:
                first.close()


if __name__ == "__main__":
    unittest.main()
