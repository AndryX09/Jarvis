import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "generate_dashboard_totp.py"


class DashboardTotpGeneratorTests(unittest.TestCase):
    def test_generator_creates_base32_secret_and_pairing_uri(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "dashboard-totp"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(GENERATOR),
                    "--output",
                    str(output),
                    "--issuer",
                    "Jarvis",
                    "--account",
                    "andry",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            secret = output.read_text(encoding="ascii").strip()

        self.assertRegex(secret, r"^[A-Z2-7]{32}$")
        self.assertIn("otpauth://totp/Jarvis%3Aandry?", completed.stdout)
        self.assertIn(f"secret={secret}", completed.stdout)
        self.assertIn("digits=6", completed.stdout)
        self.assertIn("period=30", completed.stdout)
        self.assertIsNone(re.search(r"secret=[A-Z2-7]+", completed.stderr))


if __name__ == "__main__":
    unittest.main()
