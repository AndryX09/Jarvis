import unittest
from pathlib import Path


class ReleaseContractTests(unittest.TestCase):
    def test_release_metadata_and_documentation_are_v140(self):
        root = Path(__file__).resolve().parents[1]
        package_init = (root / "app" / "__init__.py").read_text(encoding="utf-8")
        readme = (root / "README.md").read_text(encoding="utf-8")

        self.assertIn("Jarvis Core v1.4.0 package", package_init)
        self.assertNotIn("v1.1", package_init)
        self.assertTrue(readme.startswith("# Jarvis Core v1.4.0\n"))
        self.assertIn("`read_organization_policy`", readme)
        self.assertIn("Sistema — Acquisizione e triage.md", readme)
        self.assertIn("pending → ready", readme)
        self.assertIn("There is deliberately no delete tool.", readme)
        self.assertIn("## Streamable HTTP transport", readme)
        self.assertIn("JARVIS_TRANSPORT=streamable-http", readme)
        self.assertIn("http://127.0.0.1:8765/mcp", readme)
        self.assertIn("JARVIS_HTTP_ALLOWED_HOSTS", readme)
        self.assertIn("TLS is deliberately not terminated by Jarvis", readme)


if __name__ == "__main__":
    unittest.main()
