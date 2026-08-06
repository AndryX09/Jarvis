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
        self.assertEqual(
            config.allowed_origins,
            ("http://127.0.0.1:*", "http://localhost:*"),
        )
        self.assertFalse(config.http_mcp_enabled)
        self.assertEqual(config.mcp_bearer_token_file, "")
        self.assertEqual(config.dashboard_totp_secret_file, "")
        self.assertEqual(config.dashboard_trusted_proxy_peers, ())
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
                "JARVIS_HTTP_ALLOWED_ORIGINS": (
                    "http://127.0.0.1:*,https://jarvis.dvdbnc.dpdns.org"
                ),
                "JARVIS_HTTP_MCP_ENABLED": "true",
                "JARVIS_MCP_BEARER_TOKEN_FILE": "/run/secrets/jarvis-mcp-token",
                "JARVIS_DASHBOARD_TOTP_SECRET_FILE": "/run/secrets/jarvis-dashboard-totp",
                "JARVIS_DASHBOARD_TRUSTED_PROXY_PEERS": "172.17.0.1",
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
        self.assertEqual(
            config.allowed_origins,
            ("http://127.0.0.1:*", "https://jarvis.dvdbnc.dpdns.org"),
        )
        self.assertTrue(config.http_mcp_enabled)
        self.assertEqual(
            config.mcp_bearer_token_file,
            "/run/secrets/jarvis-mcp-token",
        )
        self.assertEqual(
            config.dashboard_totp_secret_file,
            "/run/secrets/jarvis-dashboard-totp",
        )
        self.assertEqual(config.dashboard_trusted_proxy_peers, ("172.17.0.1",))

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

    def test_streamable_http_rejects_empty_allowed_origins(self):
        with self.assertRaisesRegex(ValueError, "JARVIS_HTTP_ALLOWED_ORIGINS"):
            load_runtime_config(
                {
                    "JARVIS_TRANSPORT": "streamable-http",
                    "JARVIS_HTTP_ALLOWED_ORIGINS": " , ",
                }
            )

    def test_dashboard_rejects_non_ip_trusted_proxy_peer(self):
        with self.assertRaisesRegex(ValueError, "JARVIS_DASHBOARD_TRUSTED_PROXY_PEERS"):
            load_runtime_config(
                {"JARVIS_DASHBOARD_TRUSTED_PROXY_PEERS": "proxy.example.com"}
            )

    def test_unknown_http_mcp_enabled_value_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "JARVIS_HTTP_MCP_ENABLED"):
            load_runtime_config({"JARVIS_HTTP_MCP_ENABLED": "yes"})

    def test_enabled_http_mcp_requires_bearer_token_file(self):
        with self.assertRaisesRegex(ValueError, "JARVIS_MCP_BEARER_TOKEN_FILE"):
            load_runtime_config({"JARVIS_HTTP_MCP_ENABLED": "true"})


if __name__ == "__main__":
    unittest.main()
