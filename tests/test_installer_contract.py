import subprocess
import unittest
from pathlib import Path


class InstallerContractTests(unittest.TestCase):
    def test_launcher_template_uses_shared_rollout_lock_and_immutable_image_id(self):
        root = Path(__file__).resolve().parents[1]
        launcher = (root / "release" / "run-jarvis-main-v1.3.3.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('exec 9>"$rollout_lock"', launcher)
        self.assertIn("flock -s -n 9", launcher)
        self.assertEqual(launcher.count("IMAGE_ID_PLACEHOLDER"), 1)
        self.assertNotIn("jarvis-core:1.3.3", launcher)
        self.assertNotIn("jarvis-core:1.3.2", launcher)

    def test_installer_uses_pinned_transactional_release_helper(self):
        root = Path(__file__).resolve().parents[1]
        installer_path = root / "release" / "install-jarvis-1.3.3.sh"
        installer = installer_path.read_text(encoding="utf-8")

        syntax = subprocess.run(
            ["sh", "-n", str(installer_path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stdout)
        self.assertIn("expected_verifier=", installer)
        self.assertIn("mktemp -d", installer)
        self.assertIn("install -m 0400", installer)
        self.assertIn('"$verifier" snapshot-list', installer)
        self.assertIn('"$verifier" verify-new-snapshot', installer)
        self.assertIn('"$verifier" extract', installer)
        self.assertIn('"$verifier" activate', installer)
        self.assertIn('"$verifier" render-launcher', installer)
        self.assertIn("rollback_image_id=", installer)
        self.assertIn(
            'expected_rollback_image_id="sha256:a12644a9cca5a874b87f7c7fc10eaa389380003a136d25feb6b3a2d9bd242ed4"',
            installer,
        )
        self.assertNotIn("ROLLBACK_IMAGE_ID_PLACEHOLDER", installer)
        self.assertIn('exec 9>"$rollout_lock"', installer)
        self.assertIn("flock -x -n 9", installer)
        self.assertLess(installer.index("gate_launcher"), installer.index("flock -x -n 9"))
        self.assertIn("docker image inspect --format '{{.Id}}' jarvis-core:1.3.2", installer)
        self.assertIn("['version'] == '1.3.2'", installer)
        self.assertIn('  "$expected_rollback_image_id" \\', installer)
        self.assertIn('  "$new_image_id" \\', installer)
        self.assertNotIn("docker run --rm jarvis-core:1.3.2", installer)
        self.assertNotIn("docker run --rm jarvis-core:1.3.3", installer)
        self.assertNotIn("tar -x", installer)
        self.assertNotIn('mv "$candidate_launcher"', installer)


if __name__ == "__main__":
    unittest.main()
