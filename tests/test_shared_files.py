from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


class SharedMockUpstreamTests(unittest.TestCase):
    """The demo manifests each mount a local mock_vllm.py.

    They are intentionally duplicated because Kustomize cannot mount a file
    outside its overlay root. This test fails if the copies drift apart.
    """

    def test_all_mock_vllm_copies_are_identical(self) -> None:
        paths = [
            PROJECT_ROOT / "deploy" / "observability" / "mock_vllm.py",
            PROJECT_ROOT / "k8s" / "hpa-queue-demo" / "mock_vllm.py",
            PROJECT_ROOT / "k8s" / "tls-demo" / "mock_vllm.py",
        ]
        digests = {
            hashlib.sha256(path.read_bytes()).hexdigest() for path in paths if path.is_file()
        }
        self.assertEqual(len(digests), 1, "mock_vllm.py copies have drifted")


if __name__ == "__main__":
    unittest.main()
