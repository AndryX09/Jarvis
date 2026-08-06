import sys
import unittest
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_ROOT))

from runtime_config import load_runtime_config


class RuntimeConfigTests(unittest.TestCase):
    def test_default_transport_remains_stdio(self):
        config = load_runtime_config({})

        self.assertEqual(config.transport, "stdio")
        self.assertEqual(config.host, "127.0.0.1")
        self.assertEqual(config.port, 8000)
        self.assertEqual(config.streamable_http_path, "/mcp")
        self.assertEqual(config.mcp_allowed_hosts, ("127.0.0.1:*", "localhost:*"))
        self.assertFalse(config.http_mcp_enabled)
        self.assertEqual(config.web_note_scope, "none")
        self.assertEqual(config.web_note_password_file, "")

    def test_streamable_http_uses_explicit_bind_and_allowed_hosts(self):
        config = load_runtime_config(
            {
                "JARVIS_TRANSPORT": "streamable-http",
                "JARVIS_HTTP_HOST": "0.0.0.0",
                "JARVIS_HTTP_PORT": "8765",
                "JARVIS_HTTP_ALLOWED_HOSTS": (
                    "127.0.0.1:*,localhost:*,jarvis.dvdbnc.dpdns.org"
                ),
                "JARVIS_MCP_ALLOWED_HOSTS": "127.0.0.1:*,localhost:*",
                "JARVIS_HTTP_MCP_ENABLED": "true",
            }
        )

        self.assertEqual(config.transport, "streamable-http")
        self.assertEqual(config.host, "0.0.0.0")
        self.assertEqual(config.port, 8765)
        self.assertEqual(
            config.allowed_hosts,
            (
                "127.0.0.1:*",
                "localhost:*",
                "jarvis.dvdbnc.dpdns.org",
            ),
        )
        self.assertEqual(
            config.mcp_allowed_hosts,
            ("127.0.0.1:*", "localhost:*"),
        )
        self.assertTrue(config.http_mcp_enabled)

    def test_enabled_web_note_scope_requires_password_file(self):
        with self.assertRaisesRegex(ValueError, "JARVIS_WEB_NOTE_PASSWORD_FILE"):
            load_runtime_config({"JARVIS_WEB_NOTE_SCOPE": "panoramas"})

    def test_unknown_web_note_scope_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "JARVIS_WEB_NOTE_SCOPE"):
            load_runtime_config({"JARVIS_WEB_NOTE_SCOPE": "everything"})

    def test_unknown_transport_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "JARVIS_TRANSPORT"):
            load_runtime_config({"JARVIS_TRANSPORT": "http"})

    def test_http_port_outside_tcp_range_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "JARVIS_HTTP_PORT"):
            load_runtime_config(
                {
                    "JARVIS_TRANSPORT": "streamable-http",
                    "JARVIS_HTTP_PORT": "0",
                }
            )

    def test_streamable_http_rejects_empty_allowed_hosts(self):
        with self.assertRaisesRegex(ValueError, "JARVIS_HTTP_ALLOWED_HOSTS"):
            load_runtime_config(
                {
                    "JARVIS_TRANSPORT": "streamable-http",
                    "JARVIS_HTTP_ALLOWED_HOSTS": " , ",
                }
            )

    def test_streamable_http_rejects_empty_mcp_allowed_hosts(self):
        with self.assertRaisesRegex(ValueError, "JARVIS_MCP_ALLOWED_HOSTS"):
            load_runtime_config(
                {
                    "JARVIS_TRANSPORT": "streamable-http",
                    "JARVIS_MCP_ALLOWED_HOSTS": " , ",
                }
            )

    def test_unknown_http_mcp_enabled_value_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "JARVIS_HTTP_MCP_ENABLED"):
            load_runtime_config({"JARVIS_HTTP_MCP_ENABLED": "yes"})


if __name__ == "__main__":
    unittest.main()
