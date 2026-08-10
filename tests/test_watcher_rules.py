import sys
import unittest
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_ROOT))

from watcher import WatchEvent
from watcher_rules import plan_event


class WatcherRulesTests(unittest.TestCase):
    def test_policy_routes_events_without_semantic_guessing(self):
        cases = (
            (
                WatchEvent("created", "AI Inbox/Idea.md", None, "a" * 64),
                ("queue_capture", "auto"),
            ),
            (
                WatchEvent("modified", "AI Inbox/Idea.md", "a" * 64, "b" * 64),
                ("queue_capture", "auto"),
            ),
            (
                WatchEvent("deleted", "AI Inbox/Idea.md", "a" * 64, None),
                ("review_required", "suggest"),
            ),
            (
                WatchEvent("modified", "Idee/Corti/Idea.md", "a" * 64, "b" * 64),
                ("review_required", "suggest"),
            ),
            (
                WatchEvent(
                    "created",
                    "AI Inbox/_fingerprint/copia.md",
                    None,
                    "a" * 64,
                ),
                ("ignore", "auto"),
            ),
            (
                WatchEvent(
                    "created",
                    "Idee/_snapshot/2026-08-09/copia.md",
                    None,
                    "a" * 64,
                ),
                ("ignore", "auto"),
            ),
        )

        for event, expected in cases:
            with self.subTest(path=event.relative_path, event=event.event_type):
                plan = plan_event(event)
                self.assertEqual((plan.action, plan.mode), expected)


if __name__ == "__main__":
    unittest.main()
