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
        self.assertIn("--read-only", launcher)
        self.assertIn("--cap-drop ALL", launcher)
        self.assertIn("--security-opt no-new-privileges", launcher)
        self.assertNotIn("0.0.0.0:${host_port}", launcher)
        self.assertNotIn("--network none", launcher)
        self.assertNotIn("jarvis-http-internal", launcher)


if __name__ == "__main__":
    unittest.main()
