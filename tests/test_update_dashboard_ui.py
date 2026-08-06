import importlib.util
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "update_dashboard_ui.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("update_dashboard_ui", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load update_dashboard_ui.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UpdateDashboardUiTests(unittest.TestCase):
    def test_container_mount_must_be_running_bind_and_read_only(self):
        self.assertTrue(SCRIPT.is_file())
        module = _load_module()
        expected_source = ROOT / "app" / "dashboard_ui"
        valid = {
            "State": {"Running": True},
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": str(expected_source),
                    "Destination": module.UI_MOUNT_DESTINATION,
                    "RW": False,
                }
            ],
            "Config": {
                "Env": [
                    f"JARVIS_DASHBOARD_UI_FILE={module.UI_CONTAINER_PATH}"
                ]
            },
        }

        module.validate_container_inspect(valid, expected_source)
        for field, value, message in (
            ("running", False, "non è in esecuzione"),
            ("type", "volume", "bind mount"),
            ("rw", True, "sola lettura"),
        ):
            changed = {
                "State": dict(valid["State"]),
                "Mounts": [dict(valid["Mounts"][0])],
                "Config": {"Env": list(valid["Config"]["Env"])},
            }
            if field == "running":
                changed["State"]["Running"] = value
            elif field == "type":
                changed["Mounts"][0]["Type"] = value
            else:
                changed["Mounts"][0]["RW"] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, message):
                    module.validate_container_inspect(changed, expected_source)

    def test_fast_update_rejects_git_symlink_mode(self):
        self.assertTrue(SCRIPT.is_file())
        module = _load_module()

        module.validate_git_object_mode("100644")
        with self.assertRaisesRegex(ValueError, "regular Git file"):
            module.validate_git_object_mode("120000")

    def test_failed_post_merge_check_rolls_back_previous_head(self):
        self.assertTrue(SCRIPT.is_file())
        module = _load_module()
        runner = mock.Mock()

        with mock.patch.object(module, "_run", runner):
            with self.assertRaisesRegex(ValueError, "health check failed"):
                module._merge_with_rollback(
                    ROOT,
                    "new-head",
                    "old-head",
                    lambda: (_ for _ in ()).throw(ValueError("health check failed")),
                )

        self.assertEqual(
            [call.args[0] for call in runner.call_args_list],
            [
                ["git", "merge", "--ff-only", "new-head"],
                ["git", "reset", "--hard", "old-head"],
            ],
        )

    def test_fast_update_requires_the_expected_branch(self):
        self.assertTrue(SCRIPT.is_file())
        module = _load_module()

        module.validate_branch("v1.4.0-http", "v1.4.0-http")
        with self.assertRaisesRegex(ValueError, "branch inatteso"):
            module.validate_branch("main", "v1.4.0-http")

    def test_fast_update_accepts_only_the_dashboard_html(self):
        self.assertTrue(SCRIPT.is_file())
        module = _load_module()

        module.validate_changed_paths(["app/dashboard_ui/dashboard.html"])
        with self.assertRaisesRegex(ValueError, "deploy completo"):
            module.validate_changed_paths(
                ["app/dashboard_ui/dashboard.html", "app/server.py"]
            )

    def test_fast_update_validates_required_ui_hooks(self):
        self.assertTrue(SCRIPT.is_file())
        module = _load_module()
        valid = (
            '<body data-dashboard="read-only">'
            '<form action="/logout"></form>'
            '<script>fetch("/api/dashboard/status")</script>'
            "</body>"
        ).encode("utf-8")

        module.validate_ui_bytes(valid)
        with self.assertRaisesRegex(ValueError, "required marker"):
            module.validate_ui_bytes(b"<!doctype html><p>incomplete</p>")
        with self.assertRaisesRegex(ValueError, "too large"):
            module.validate_ui_bytes(b"x" * (module.MAX_UI_BYTES + 1))


if __name__ == "__main__":
    unittest.main()
