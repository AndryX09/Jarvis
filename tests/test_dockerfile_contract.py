import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DockerfileContractTests(unittest.TestCase):
    def test_runtime_user_can_read_application_files_with_restrictive_build_context_modes(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        copy_index = dockerfile.index("COPY app/ /app/")
        permissions_index = dockerfile.index("RUN chmod -R a+rX /app")
        user_index = dockerfile.index("USER 10001:10001")
        self.assertLess(copy_index, permissions_index)
        self.assertLess(permissions_index, user_index)


if __name__ == "__main__":
    unittest.main()
