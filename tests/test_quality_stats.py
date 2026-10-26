from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.quality_stats import (  # noqa: E402
    PairedStats,
    cohens_kappa,
    collect,
    exact_binomial_two_sided,
    paired_stats,
    wilson_interval,
)


class WilsonIntervalTests(unittest.TestCase):
    def test_known_interval(self) -> None:
        low, high = wilson_interval(50, 100)
        self.assertAlmostEqual(low, 0.4038, places=3)
        self.assertAlmostEqual(high, 0.5962, places=3)

    def test_empty_sample(self) -> None:
        self.assertEqual(wilson_interval(0, 0), (0.0, 0.0))

    def test_rejects_impossible_counts(self) -> None:
        with self.assertRaises(ValueError):
            wilson_interval(11, 10)


class McNemarTests(unittest.TestCase):
    def test_six_discordant_pairs_split_zero_six(self) -> None:
        self.assertAlmostEqual(exact_binomial_two_sided(0, 6), 0.03125)

    def test_symmetric_split_is_not_significant(self) -> None:
        self.assertEqual(exact_binomial_two_sided(11, 22), 1.0)
        self.assertEqual(exact_binomial_two_sided(3, 6), 1.0)


class KappaTests(unittest.TestCase):
    def test_perfect_agreement(self) -> None:
        self.assertEqual(cohens_kappa([True, False, True], [True, False, True]), 1.0)

    def test_chance_level_agreement(self) -> None:
        self.assertAlmostEqual(
            cohens_kappa([True, True, False, False], [True, False, True, False]),
            0.0,
        )


class PairedStatsTests(unittest.TestCase):
    def test_counts_fixed_and_broken_from_paired_outcomes(self) -> None:
        baseline = {
            "a": {"prediction": "A", "correct": True},
            "b": {"prediction": "B", "correct": True},
            "c": {"prediction": "C", "correct": False},
            "d": {"prediction": "D", "correct": False},
        }
        model = {
            "a": {"prediction": "A", "correct": True},   # both correct
            "b": {"prediction": "C", "correct": False},  # broken
            "c": {"prediction": "C", "correct": True},   # fixed
            "d": {"prediction": "D", "correct": False},  # both wrong
        }
        stats = paired_stats(name="synthetic", model_results=model, baseline_results=baseline)
        self.assertIsInstance(stats, PairedStats)
        self.assertEqual((stats.correct, stats.attempted), (2, 4))
        self.assertEqual((stats.fixed, stats.broken), (1, 1))
        self.assertEqual(stats.mcnemar_p, 1.0)

class CurrentEvidenceTests(unittest.TestCase):
    def test_current_int4_report_is_self_consistent(self) -> None:
        rows = collect(
            PROJECT_ROOT / "benchmark" / "eval",
            "int4",
            (("Self INT4", "int4"),),
        )
        row = rows[0]
        self.assertEqual((row.correct, row.attempted), (142, 200))
        self.assertEqual(row.agreement, 1.0)
        self.assertEqual((row.fixed, row.broken), (0, 0))
