from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from llm8g.benchmarking import BenchmarkProtocol  # noqa: E402
from llm8g.evaluation import Case, Evaluator  # noqa: E402
from llm8g.evaluation.scoring import normalize, score  # noqa: E402
from llm8g.quantization import ArtifactManifest  # noqa: E402


class _Runner:
    def run(self, case: Case):
        return case.prompt.upper(), 0.01, {"total_tokens": 2}


class DomainPackageTests(unittest.TestCase):
    def test_evaluator_is_resumable_and_manifest_bound(self) -> None:
        cases = [Case("a", "yes", "YES"), Case("b", "no", "NO")]
        report = Evaluator(_Runner()).run(cases, label="fake", model="fake")
        self.assertEqual(report.summary()["correct"], 2)
        resumed = Evaluator(_Runner()).run(cases, label="fake", model="fake", resume=report)
        self.assertEqual(len(resumed.results), 2)

    def test_scoring_keeps_structured_answers_stable(self) -> None:
        self.assertEqual(normalize("```json\n{\"a\": 1}\n```"), '{"a":1}')
        self.assertTrue(score({"expected": ["AX-19"], "match": "contains"}, "key AX-19"))

    def test_artifact_manifest_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "b.txt").write_text("b", encoding="utf-8")
            (root / "a.txt").write_text("a", encoding="utf-8")
            manifest = ArtifactManifest.from_directory(
                root,
                name="demo",
                source_model="base",
                algorithm="fake",
                algorithm_version="1",
            )
            self.assertEqual([row[0] for row in manifest.files], ["a.txt", "b.txt"])
            self.assertEqual(manifest.total_bytes, 2)

    def test_protocol_comparison_is_exact(self) -> None:
        protocol = BenchmarkProtocol("p", "vllm", "1", "m", "gpu", 10, 5, 1, 3)
        self.assertTrue(protocol.comparable_with(protocol))
        other = BenchmarkProtocol("p", "vllm", "1", "m", "gpu", 10, 6, 1, 3)
        self.assertFalse(protocol.comparable_with(other))


if __name__ == "__main__":
    unittest.main()

