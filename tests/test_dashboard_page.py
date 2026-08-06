import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "app"


class DashboardPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(APP_ROOT))

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(str(APP_ROOT))
        sys.modules.pop("dashboard_page", None)

    def test_default_dashboard_is_loaded_from_an_html_file(self):
        module = importlib.import_module("dashboard_page")

        page_path = getattr(module, "DEFAULT_DASHBOARD_PAGE_PATH", None)
        loader = getattr(module, "load_dashboard_page_html", None)

        self.assertIsInstance(page_path, Path)
        self.assertTrue(page_path.is_file())
        self.assertTrue(callable(loader))
        html = loader()
        self.assertIn("Processi Jarvis", html)
        self.assertIn('data-dashboard="read-only"', html)

    def test_custom_dashboard_rejects_symbolic_links(self):
        module = importlib.import_module("dashboard_page")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            page = root / "dashboard.html"
            link = root / "dashboard-link.html"
            page.write_text("safe page", encoding="utf-8")
            try:
                link.symlink_to(page)
            except OSError:
                self.skipTest("symbolic links are unavailable on this platform")

            with self.assertRaisesRegex(ValueError, "symbolic link"):
                module.load_dashboard_page_html(str(link))

    def test_custom_dashboard_rejects_oversized_files(self):
        module = importlib.import_module("dashboard_page")
        with tempfile.TemporaryDirectory() as temporary:
            page = Path(temporary) / "dashboard.html"
            page.write_bytes(b"x" * (module.DASHBOARD_PAGE_MAX_BYTES + 1))

            with mock.patch.object(
                Path,
                "read_bytes",
                side_effect=AssertionError("oversized file must not be read in full"),
            ):
                with self.assertRaisesRegex(ValueError, "too large"):
                    module.load_dashboard_page_html(str(page))

if __name__ == "__main__":
    unittest.main()
