import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.import_keep import import_keep_archive, inspect_keep_archive
from app.vault_core import JarvisError, list_captures, read_capture


class KeepImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.state.mkdir()
        self.archive = self.root / "takeout.zip"
        with zipfile.ZipFile(self.archive, "w") as output:
            output.writestr(
                "Takeout/Keep/Idea.json",
                json.dumps(
                    {
                        "title": "Idea video",
                        "textContent": "Una descrizione concreta.",
                        "color": "YELLOW",
                        "isPinned": True,
                        "isArchived": False,
                        "isTrashed": False,
                        "createdTimestampUsec": 1_700_000_000_000_000,
                        "userEditedTimestampUsec": 1_700_000_100_000_000,
                        "labels": [{"name": "Video"}],
                    },
                    ensure_ascii=False,
                ),
            )
            output.writestr(
                "Takeout/Keep/Lista.json",
                json.dumps(
                    {
                        "title": "Lista",
                        "listContent": [
                            {"text": "Prima voce", "isChecked": False},
                            {"text": "Seconda voce", "isChecked": True},
                        ],
                        "attachments": [
                            {"filePath": "allegato.png", "mimetype": "image/png"}
                        ],
                        "color": "DEFAULT",
                        "isPinned": False,
                        "isArchived": True,
                        "isTrashed": False,
                        "createdTimestampUsec": 1_700_000_200_000_000,
                        "userEditedTimestampUsec": 1_700_000_300_000_000,
                    },
                    ensure_ascii=False,
                ),
            )
            output.writestr("Takeout/Keep/allegato.png", b"fake-png")

    def tearDown(self):
        self.temp.cleanup()

    def test_inspection_reads_schema_without_writing_state(self):
        result = import_keep_archive(
            self.archive, self.state, dry_run=True, limit=None
        )

        self.assertEqual(result["notes_found"], 2)
        self.assertEqual(result["attachment_references"], 1)
        self.assertEqual(result["created"], 0)
        self.assertFalse(result["archive_preserved"])
        self.assertFalse((self.state / "captures").exists())
        self.assertFalse((self.state / "imports").exists())

    def test_import_preserves_archive_and_creates_deduplicated_captures(self):
        first = import_keep_archive(
            self.archive, self.state, dry_run=False, limit=None
        )
        second = import_keep_archive(
            self.archive, self.state, dry_run=False, limit=None
        )

        archive_hash = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        preserved = self.state / "imports" / "google-keep" / f"{archive_hash}.zip"
        self.assertTrue(preserved.is_file())
        self.assertEqual(hashlib.sha256(preserved.read_bytes()).hexdigest(), archive_hash)
        self.assertEqual(first["created"], 2)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["duplicates"], 2)
        captures = list_captures(self.state)["captures"]
        self.assertEqual(len(captures), 2)

        records = [read_capture(self.state, item["capture_id"]) for item in captures]
        list_record = next(record for record in records if record["title"] == "Lista")
        self.assertIn("- [ ] Prima voce", list_record["content"])
        self.assertIn("- [x] Seconda voce", list_record["content"])
        self.assertIn("allegato.png (image/png)", list_record["content"])
        self.assertIn("keep:archived", list_record["labels"])
        idea_record = next(record for record in records if record["title"] == "Idea video")
        self.assertIn("Video", idea_record["labels"])
        self.assertIn("keep:pinned", idea_record["labels"])
        self.assertEqual(idea_record["source_created_utc"], "2023-11-14T22:13:20Z")

    def test_limit_imports_only_requested_sample(self):
        result = import_keep_archive(
            self.archive, self.state, dry_run=False, limit=1
        )
        self.assertEqual(result["notes_found"], 2)
        self.assertEqual(result["notes_selected"], 1)
        self.assertEqual(result["created"], 1)

    def test_json_outside_keep_is_rejected_before_writes(self):
        unsafe = self.root / "unsafe.zip"
        with zipfile.ZipFile(unsafe, "w") as output:
            output.writestr("Other/data.json", "{}")
        with self.assertRaises(JarvisError):
            inspect_keep_archive(unsafe)
        self.assertFalse((self.state / "captures").exists())


if __name__ == "__main__":
    unittest.main()
