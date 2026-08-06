import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "generate_mcp_bearer_token.py"


class McpBearerTokenGeneratorTests(unittest.TestCase):
    def test_generator_creates_urlsafe_token_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "mcp-token"
            completed = subprocess.run(
                [sys.executable, str(GENERATOR), "--output", str(output)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            token = output.read_text(encoding="ascii").strip()
            mode = output.stat().st_mode & 0o777

            repeated = subprocess.run(
                [sys.executable, str(GENERATOR), "--output", str(output)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertRegex(token, r"^[A-Za-z0-9_-]{43}$")
        self.assertIn("Bearer token (shown once):", completed.stdout)
        self.assertIn(token, completed.stdout)
        self.assertIsNone(re.search(re.escape(token), completed.stderr))
        self.assertNotEqual(repeated.returncode, 0)
        self.assertIn("Refusing to overwrite", repeated.stderr)
        if os.name != "nt":
            self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
