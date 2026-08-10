import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_ROOT))

from vault_core import JarvisError, list_captures, read_capture
from watcher import WatchEvent
from watcher_pipeline import WatcherProcessor


class WatcherPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.vault_root = self.root / "vault"
        self.state_root = self.root / "state"
        self.inbox = self.vault_root / "AI Inbox"
        self.inbox.mkdir(parents=True)
        self.state_root.mkdir()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_inbox_event_creates_one_deduplicated_pending_capture(self):
        note = self.inbox / "Idea.md"
        content = "Una cattura esplicita"
        note.write_text(content, encoding="utf-8")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        originals = self.state_root / "watcher-originals"
        originals.mkdir()
        (originals / f"{digest}.md").write_text(content, encoding="utf-8")
        note.write_text("contenuto successivo", encoding="utf-8")
        event = WatchEvent("created", "AI Inbox/Idea.md", None, digest)
        processor = WatcherProcessor(self.vault_root, self.state_root)

        first = processor.process(event)
        second = processor.process(event)
        captures = list_captures(self.state_root, status="all")["captures"]

        self.assertEqual(first.action, "queue_capture")
        self.assertTrue(first.capture_created)
        self.assertFalse(second.capture_created)
        self.assertEqual(len(captures), 1)
        self.assertEqual(captures[0]["status"], "pending")
        self.assertEqual(read_capture(self.state_root, first.capture_id)["content"], content)

    def test_missing_preserved_content_fails_closed_without_capture(self):
        note = self.inbox / "Idea.md"
        note.write_text("corrente", encoding="utf-8")
        stale_digest = hashlib.sha256(b"precedente").hexdigest()
        event = WatchEvent("modified", "AI Inbox/Idea.md", stale_digest, stale_digest)
        processor = WatcherProcessor(self.vault_root, self.state_root)

        with self.assertRaisesRegex(JarvisError, "preserved"):
            processor.process(event)
        captures = list_captures(self.state_root, status="all")["captures"]

        self.assertEqual(captures, [])

    def test_preserved_content_read_has_no_symlink_swap_window(self):
        content = b"contenuto originale"
        digest = hashlib.sha256(content).hexdigest()
        originals = self.state_root / "watcher-originals"
        originals.mkdir()
        preserved = originals / f"{digest}.md"
        preserved.write_bytes(content)
        external = self.root / "external.md"
        external.write_bytes(content)
        event = WatchEvent("created", "AI Inbox/Idea.md", None, digest)
        processor = WatcherProcessor(self.vault_root, self.state_root)
        original_read_bytes = Path.read_bytes

        def swap_before_path_read(path: Path) -> bytes:
            if path == preserved:
                preserved.unlink()
                try:
                    os.symlink(external, preserved)
                except (OSError, NotImplementedError):
                    self.skipTest("symbolic links are unavailable")
            return original_read_bytes(path)

        with mock.patch.object(Path, "read_bytes", swap_before_path_read):
            result = processor.process(event)

        self.assertFalse(preserved.is_symlink())
        self.assertTrue(result.capture_created)

    def test_permanently_invalid_inbox_content_requires_suggest_mode(self):
        content = b"\xff"
        digest = hashlib.sha256(content).hexdigest()
        originals = self.state_root / "watcher-originals"
        originals.mkdir()
        (originals / f"{digest}.md").write_bytes(content)
        event = WatchEvent("created", "AI Inbox/NonUtf8.md", None, digest)

        result = WatcherProcessor(self.vault_root, self.state_root).process(event)

        self.assertEqual(result.action, "review_required")
        self.assertEqual(result.mode, "suggest")
        self.assertEqual(result.reason, "capture_content_is_not_utf8")


if __name__ == "__main__":
    unittest.main()
