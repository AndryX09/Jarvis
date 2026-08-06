import unittest
from pathlib import Path


class HttpLauncherContractTests(unittest.TestCase):
    def test_http_launcher_is_loopback_only_and_uses_bridge_network(self):
        root = Path(__file__).resolve().parents[1]
        launcher = (
            root / "release" / "run-jarvis-http-main-v1.4.0.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("IMAGE_ID_PLACEHOLDER", launcher)
        self.assertIn("docker network inspect", launcher)
        self.assertIn(
            'network_name="${JARVIS_HTTP_DOCKER_NETWORK:-bridge}"', launcher
        )
        self.assertIn('--publish "127.0.0.1:${host_port}:${container_port}"', launcher)
        self.assertIn("JARVIS_TRANSPORT=streamable-http", launcher)
        self.assertIn("JARVIS_HTTP_HOST=0.0.0.0", launcher)
        self.assertIn("JARVIS_HTTP_PORT=${container_port}", launcher)
        self.assertIn("JARVIS_HTTP_ALLOWED_HOSTS=${allowed_hosts}", launcher)
        self.assertIn(
            'mcp_allowed_hosts="${JARVIS_MCP_ALLOWED_HOSTS:-127.0.0.1:*,localhost:*}"',
            launcher,
        )
        self.assertIn("JARVIS_MCP_ALLOWED_HOSTS=${mcp_allowed_hosts}", launcher)
        self.assertIn(
            'http_mcp_enabled="${JARVIS_HTTP_MCP_ENABLED:-false}"', launcher
        )
        self.assertIn("JARVIS_HTTP_MCP_ENABLED=${http_mcp_enabled}", launcher)
        self.assertIn('web_note_scope="${JARVIS_WEB_NOTE_SCOPE:-none}"', launcher)
        self.assertIn("panoramas|all-visible-markdown", launcher)
        self.assertIn("JARVIS_WEB_NOTE_SCOPE=${web_note_scope}", launcher)
        self.assertIn("JARVIS_WEB_NOTE_PASSWORD_FILE=/run/secrets/jarvis-web-note-password", launcher)
        self.assertIn("dst=/run/secrets/jarvis-web-note-password,readonly", launcher)
        self.assertNotIn("JARVIS_WEB_NOTE_PASSWORD=", launcher)
        self.assertIn("--read-only", launcher)
        self.assertIn("--cap-drop ALL", launcher)
        self.assertIn("--security-opt no-new-privileges", launcher)
        self.assertNotIn("0.0.0.0:${host_port}", launcher)
        self.assertNotIn("--network none", launcher)
        self.assertNotIn("jarvis-http-internal", launcher)


if __name__ == "__main__":
    unittest.main()
