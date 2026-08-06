import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
sys.path.insert(0, str(APP))
try:
    from dashboard_auth import (
        create_session_token,
        load_totp_secret,
        validate_session_token,
        verify_totp,
    )
finally:
    sys.path.remove(str(APP))


class DashboardAuthTests(unittest.TestCase):
    def test_session_token_is_valid_within_its_lifetime(self):
        secret = b"12345678901234567890"
        token = create_session_token(secret, now=1_000)

        self.assertTrue(
            validate_session_token(secret, token, now=1_100, max_age_seconds=28_800)
        )

    def test_verify_totp_accepts_rfc_code_for_current_time_step(self):
        secret = b"12345678901234567890"

        self.assertTrue(verify_totp(secret, "287082", now=59, window=0))

    def test_load_totp_secret_accepts_160_bit_base32_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            secret_file = Path(temporary) / "totp-secret"
            secret_file.write_text(
                "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ\n",
                encoding="ascii",
            )

            secret = load_totp_secret(str(secret_file))

        self.assertEqual(secret, b"12345678901234567890")


if __name__ == "__main__":
    unittest.main()
