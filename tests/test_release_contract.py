import unittest
from pathlib import Path


class ReleaseContractTests(unittest.TestCase):
    def test_release_metadata_and_documentation_are_v133(self):
        root = Path(__file__).resolve().parents[1]
        package_init = (root / "app" / "__init__.py").read_text(encoding="utf-8")
        readme = (root / "README.md").read_text(encoding="utf-8")

        self.assertIn("Jarvis Core v1.3.3 package", package_init)
        self.assertNotIn("v1.1", package_init)
        self.assertTrue(readme.startswith("# Jarvis Core v1.3.3\n"))
        self.assertIn("`read_organization_policy`", readme)
        self.assertIn("Sistema — Acquisizione e triage.md", readme)
        self.assertIn("pending → ready", readme)
        self.assertIn("There is deliberately no delete tool.", readme)


if __name__ == "__main__":
    unittest.main()
