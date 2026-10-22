from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.freeform_eval import normalize, score  # noqa: E402


class FreeformScoringTests(unittest.TestCase):
    def test_normalizes_whitespace_and_code_fences(self) -> None:
        self.assertEqual(normalize("```json\n{\"a\": 1}\n```"), '{"a":1}')

    def test_exact_match_is_whitespace_insensitive(self) -> None:
        self.assertTrue(score({"expected": ["[1, 9, 25]"], "match": "exact"}, "[1,9,25]"))
        self.assertFalse(score({"expected": ["不会"], "match": "exact"}, "会"))

    def test_contains_and_regex(self) -> None:
        self.assertTrue(
            score({"expected": ["AX-19-KQ"], "match": "contains"}, "密钥是 AX-19-KQ。")
        )
        self.assertTrue(
            score({"expected": [r"^\d+$"], "match": "regex"}, " 256 ")
        )

    def test_committed_case_file_is_valid(self) -> None:
        path = PROJECT_ROOT / "benchmark" / "eval" / "freeform-cases.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], 1)
        self.assertGreaterEqual(len(manifest["cases"]), 10)
        ids = [case["id"] for case in manifest["cases"]]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
