from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from ceval_quality_eval import (  # noqa: E402
    build_prompt,
    load_ceval_split,
    parse_prediction,
    select_stratified_cases,
    summarize,
)


CEVAL_ZIP = Path("/mnt/e/AI-Inference-Lab/datasets/ceval.zip")


class CEvalQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.grouped = load_ceval_split(CEVAL_ZIP, "val")

    def test_validation_split_has_answers_and_expected_subjects(self) -> None:
        self.assertEqual(len(self.grouped), 52)
        self.assertTrue(all(rows for rows in self.grouped.values()))
        self.assertTrue(
            all(row["answer"] in "ABCD" for rows in self.grouped.values() for row in rows)
        )

    def test_selects_exactly_200_balanced_deterministic_cases(self) -> None:
        left = select_stratified_cases(self.grouped, samples=200, seed=20260920)
        right = select_stratified_cases(self.grouped, samples=200, seed=20260920)
        self.assertEqual(left, right)
        self.assertEqual(len(left), 200)
        counts = Counter(case["subject"] for case in left)
        self.assertEqual(set(counts.values()), {3, 4})
        self.assertEqual(len({case["case_id"] for case in left}), 200)

    def test_prompt_requests_one_letter_and_contains_options(self) -> None:
        case = select_stratified_cases(self.grouped, samples=200, seed=20260920)[0]
        prompt = build_prompt(case)
        self.assertIn("只输出一个大写字母", prompt)
        for choice in "ABCD":
            self.assertIn(f"{choice}. {case[choice]}", prompt)

    def test_prediction_parser(self) -> None:
        examples = {
            "A": "A",
            "答案是 B。": "B",
            "选项：C": "C",
            "我选择 D，因为": "D",
            "无法判断": None,
        }
        for text, expected in examples.items():
            with self.subTest(text=text):
                self.assertEqual(parse_prediction(text), expected)

    def test_summary_counts_invalid_as_incorrect(self) -> None:
        results = [
            {
                "subject": "demo",
                "prediction": "A",
                "correct": True,
                "latency_seconds": 1.0,
            },
            {
                "subject": "demo",
                "prediction": None,
                "correct": False,
                "latency_seconds": 3.0,
            },
        ]
        summary = summarize(results)
        self.assertEqual(summary["attempted"], 2)
        self.assertEqual(summary["valid_predictions"], 1)
        self.assertEqual(summary["correct"], 1)
        self.assertEqual(summary["accuracy"], 0.5)
        self.assertEqual(summary["invalid_prediction_rate"], 0.5)
        self.assertEqual(summary["mean_latency_seconds"], 2.0)


if __name__ == "__main__":
    unittest.main()
