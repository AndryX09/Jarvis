import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from scripts.preview_dashboard import WatcherPreviewState


ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / "scripts" / "preview_dashboard.py"


def _unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class PreviewDashboardTests(unittest.TestCase):
    def test_retry_deferred_is_not_applied_until_confirmation(self):
        watcher = WatcherPreviewState()
        after_cycle = watcher.execute("run-cycle")
        self.assertEqual(after_cycle["last_cycle"]["processed"], 2)
        self.assertEqual(after_cycle["last_cycle"]["deferred"], 1)

        pending = watcher.execute("retry-deferred")
        self.assertEqual(pending["last_cycle"]["processed"], 2)
        self.assertEqual(pending["last_cycle"]["deferred"], 1)
        self.assertEqual(pending["pending_confirmation"], "retry-deferred")

        confirmed = watcher.execute("confirm")
        self.assertEqual(confirmed["last_cycle"]["processed"], 3)
        self.assertEqual(confirmed["last_cycle"]["deferred"], 0)
        self.assertIsNone(confirmed["pending_confirmation"])

    def test_retry_failed_is_not_applied_until_confirmation(self):
        watcher = WatcherPreviewState()
        watcher.execute("run-cycle")
        watcher.execute("run-cycle")
        failed_cycle = watcher.execute("run-cycle")
        self.assertEqual(failed_cycle["last_cycle"]["processed"], 2)
        self.assertEqual(failed_cycle["last_cycle"]["errors"], 1)

        pending = watcher.execute("retry-failed")
        self.assertEqual(pending["last_cycle"]["processed"], 2)
        self.assertEqual(pending["last_cycle"]["errors"], 1)
        self.assertEqual(pending["pending_confirmation"], "retry-failed")

        confirmed = watcher.execute("confirm")
        self.assertEqual(confirmed["last_cycle"]["processed"], 3)
        self.assertEqual(confirmed["last_cycle"]["errors"], 0)
        self.assertIsNone(confirmed["pending_confirmation"])

    def test_dashboard_manual_mode_exposes_only_closed_command_grammar(self):
        html = (ROOT / "app" / "dashboard_ui" / "dashboard.html").read_text(
            encoding="utf-8"
        )

        self.assertIn('id="watcher-console"', html)
        self.assertIn('data-watcher-command="run-cycle"', html)
        self.assertIn('data-watcher-command="pause"', html)
        self.assertIn('data-watcher-command="resume"', html)
        self.assertIn('id="watcher-manual-toggle"', html)
        self.assertIn('id="watcher-manual-command"', html)
        self.assertIn('maxlength="16"', html)
        self.assertIn('["run", "run-cycle"]', html)
        self.assertIn('["pause", "pause"]', html)
        self.assertIn('["resume", "resume"]', html)
        self.assertIn('["status", "status"]', html)
        self.assertIn('["help", "help"]', html)
        self.assertIn('["clear", "clear"]', html)
        self.assertIn('["retry deferred", "retry-deferred"]', html)
        self.assertIn('["retry failed", "retry-failed"]', html)
        self.assertIn('["confirm", "confirm"]', html)
        self.assertIn('["cancel", "cancel"]', html)
        self.assertNotIn("contenteditable", html)

    def test_dashboard_echoes_manual_commands_with_safe_dom_rendering(self):
        html = (ROOT / "app" / "dashboard_ui" / "dashboard.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("function appendManualTerminalLine", html)
        self.assertIn('appendManualTerminalLine("cmd", `C:\\\\Jarvis> ${token}`)', html)
        self.assertIn("message.textContent = messageText", html)
        self.assertNotIn("innerHTML", html)

    def test_preview_reloads_html_and_serves_demo_status(self):
        self.assertTrue(PREVIEW.is_file())
        with tempfile.TemporaryDirectory() as temporary:
            page = Path(temporary) / "dashboard.html"
            page.write_text("<!doctype html><p>prima preview</p>", encoding="utf-8")
            port = _unused_loopback_port()
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(PREVIEW),
                    "--ui-file",
                    str(page),
                    "--port",
                    str(port),
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                base_url = f"http://127.0.0.1:{port}"
                deadline = time.monotonic() + 10
                while True:
                    try:
                        with urllib.request.urlopen(base_url, timeout=1) as response:
                            first = response.read().decode("utf-8")
                        break
                    except OSError:
                        if process.poll() is not None or time.monotonic() >= deadline:
                            stdout, stderr = process.communicate(timeout=2)
                            self.fail(f"preview did not start\nstdout={stdout}\nstderr={stderr}")
                        time.sleep(0.05)

                page.write_text("<!doctype html><p>seconda preview</p>", encoding="utf-8")
                with urllib.request.urlopen(base_url, timeout=2) as response:
                    second = response.read().decode("utf-8")
                with urllib.request.urlopen(
                    f"{base_url}/api/dashboard/status", timeout=2
                ) as response:
                    status = json.load(response)

                command_request = urllib.request.Request(
                    f"{base_url}/api/preview/watcher/command",
                    data=json.dumps({"command": "run-cycle"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(command_request, timeout=2) as response:
                    command_result = json.load(response)

                invalid_request = urllib.request.Request(
                    f"{base_url}/api/preview/watcher/command",
                    data=json.dumps({"command": "shell"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as rejected:
                    urllib.request.urlopen(invalid_request, timeout=2)
            finally:
                process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=2)

        self.assertIn("prima preview", first)
        self.assertIn("seconda preview", second)
        self.assertEqual(status["security"]["dashboard_mode"], "preview")
        self.assertFalse(status["security"]["http_mcp_enabled"])
        self.assertEqual(command_result["accepted_command"], "run-cycle")
        self.assertEqual(command_result["watcher"]["cycle_count"], 1)
        self.assertEqual(rejected.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
