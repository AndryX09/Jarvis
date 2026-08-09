import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_ROOT))

from mcp_auth import StaticBearerTokenVerifier, load_mcp_bearer_token


class McpBearerTokenFileTests(unittest.TestCase):
    def test_valid_single_line_token_is_loaded(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mcp-token"
            path.write_text("A" * 43 + "\n", encoding="ascii")

            self.assertEqual(load_mcp_bearer_token(str(path)), b"A" * 43)

    def test_short_token_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mcp-token"
            path.write_text("too-short", encoding="ascii")

            with self.assertRaisesRegex(ValueError, "at least 32 bytes"):
                load_mcp_bearer_token(str(path))

    def test_multiline_token_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mcp-token"
            path.write_text("A" * 43 + "\n" + "B" * 43, encoding="ascii")

            with self.assertRaisesRegex(ValueError, "one token"):
                load_mcp_bearer_token(str(path))

    def test_oversized_token_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mcp-token"
            path.write_bytes(b"A" * 513)

            with self.assertRaisesRegex(ValueError, "small regular file"):
                load_mcp_bearer_token(str(path))

    def test_symbolic_link_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "target"
            link = Path(temporary) / "mcp-token"
            target.write_bytes(b"A" * 43)
            try:
                link.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")

            with self.assertRaisesRegex(ValueError, "symbolic link"):
                load_mcp_bearer_token(str(link))


class StaticBearerTokenVerifierTests(unittest.TestCase):
    def test_matching_token_is_accepted(self):
        token = "A" * 43
        verifier = StaticBearerTokenVerifier(token.encode("ascii"))

        accepted = asyncio.run(verifier.verify_token(token))

        self.assertIsNotNone(accepted)
        self.assertEqual(accepted.client_id, "jarvis-hermes-client")
        self.assertEqual(accepted.scopes, [])

    def test_non_matching_token_is_rejected(self):
        verifier = StaticBearerTokenVerifier(b"A" * 43)

        self.assertIsNone(asyncio.run(verifier.verify_token("B" * 43)))


if __name__ == "__main__":
    unittest.main()
