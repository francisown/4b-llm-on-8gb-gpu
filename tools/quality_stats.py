#!/usr/bin/env python3
"""Paired statistics for the C-Eval quantization comparison.

The headline table in ``benchmark/eval/README.md`` reports accuracy and
per-question agreement, but neither has a confidence interval or a paired
significance test. This tool fills that gap without adding a scipy dependency:

* Wilson score interval for accuracy and agreement;
* exact McNemar test for the paired correct/incorrect outcomes;
* Cohen's kappa for the per-question answer-choice agreement.

Run it from the repository root::

    python tools/quality_stats.py

It reads ``benchmark/eval/*-ceval-val-200.json`` and prints a Markdown table.
The values are also asserted by ``tests/test_quality_stats.py`` so the math is
covered by CI.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any


EVAL_DIR = Path("benchmark/eval")
BASELINE_NAME = "bf16-reference"
DEFAULT_MODELS = (
    ("Third-party FP8", "third-party-fp8"),
    ("Self FP8 v3", "self-fp8-v3"),
    ("Self INT4-AWQ v1", "self-int4-awq-v1"),
)
Z_95 = 1.959963984540054


@dataclass(frozen=True)
class PairedStats:
    model: str
    attempted: int
    correct: int
    accuracy: float
    accuracy_ci: tuple[float, float]
    agreement: float
    agreement_ci: tuple[float, float]
    fixed: int
    broken: int
    mcnemar_p: float
    kappa: float


def wilson_interval(successes: int, total: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if total <= 0:
        return 0.0, 0.0
    if successes < 0 or successes > total:
        raise ValueError("successes must be between 0 and total")
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
        / denominator
    )
    return max(0.0, centre - margin), min(1.0, centre + margin)


def exact_binomial_two_sided(successes: int, trials: int) -> float:
    """Exact two-sided binomial test against p=0.5 (McNemar's exact test)."""
    if trials <= 0:
        return 1.0
    probabilities = [
        math.comb(trials, index) * (0.5**trials) for index in range(trials + 1)
    ]
    observed = probabilities[successes]
    # Add a small tolerance so floating-point round-off does not exclude the
    # observed outcome itself.
    return min(
        1.0,
        sum(
            probability
            for probability in probabilities
            if probability <= observed + 1e-15
        ),
    )


def cohens_kappa(
    model_labels: list[Any],
    baseline_labels: list[Any],
) -> float:
    """Cohen's kappa for two categorical label vectors (e.g. A/B/C/D)."""
    if len(model_labels) != len(baseline_labels):
        raise ValueError("vectors must have the same length")
    total = len(model_labels)
    if total == 0:
        return 0.0
    observed = sum(a == b for a, b in zip(model_labels, baseline_labels)) / total
    model_counts = Counter(model_labels)
    baseline_counts = Counter(baseline_labels)
    expected = sum(
        model_counts[label] * baseline_counts[label] / (total * total)
        for label in set(model_counts) | set(baseline_counts)
    )
    if expected >= 1.0:
        return 1.0
    return (observed - expected) / (1 - expected)


def load_results(path: Path) -> dict[str, dict[str, Any]]:
    report = json.loads(path.read_text(encoding="utf-8-sig"))
    return {row["case_id"]: row for row in report["results"]}


def paired_stats(
    *,
    name: str,
    model_results: dict[str, dict[str, Any]],
    baseline_results: dict[str, dict[str, Any]],
) -> PairedStats:
    case_ids = sorted(set(model_results) & set(baseline_results))
    if not case_ids:
        raise ValueError("the two reports have no case IDs in common")
    model_correct = [bool(model_results[case_id]["correct"]) for case_id in case_ids]
    model_predictions = [model_results[case_id]["prediction"] for case_id in case_ids]
    baseline_predictions = [baseline_results[case_id]["prediction"] for case_id in case_ids]
    correct = sum(model_correct)
    agreement = sum(
        model_results[case_id]["prediction"] == baseline_results[case_id]["prediction"]
        for case_id in case_ids
    )
    fixed = sum(
        model_results[case_id]["correct"] and not baseline_results[case_id]["correct"]
        for case_id in case_ids
    )
    broken = sum(
        not model_results[case_id]["correct"] and baseline_results[case_id]["correct"]
        for case_id in case_ids
    )
    return PairedStats(
        model=name,
        attempted=len(case_ids),
        correct=correct,
        accuracy=correct / len(case_ids),
        accuracy_ci=wilson_interval(correct, len(case_ids)),
        agreement=agreement / len(case_ids),
        agreement_ci=wilson_interval(agreement, len(case_ids)),
        fixed=fixed,
        broken=broken,
        mcnemar_p=exact_binomial_two_sided(fixed, fixed + broken),
        kappa=cohens_kappa(model_predictions, baseline_predictions),
    )


def collect(
    eval_dir: Path,
    baseline_name: str,
    models: tuple[tuple[str, str], ...],
) -> list[PairedStats]:
    baseline = load_results(eval_dir / f"{baseline_name}-ceval-val-200.json")
    rows: list[PairedStats] = []
    for label, stem in models:
        model_results = load_results(eval_dir / f"{stem}-ceval-val-200.json")
        rows.append(
            paired_stats(
                name=label,
                model_results=model_results,
                baseline_results=baseline,
            )
        )
    return rows


def render_markdown(rows: list[PairedStats]) -> str:
    lines = [
        "| Model | Accuracy (95% Wilson) | Agreement with BF16 (95% Wilson) "
        "| Fixed / broken | McNemar p | Cohen's κ |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| "
            f"{row.model} | "
            f"{row.correct}/{row.attempted} = {row.accuracy:.1%} "
            f"({row.accuracy_ci[0]:.1%}–{row.accuracy_ci[1]:.1%}) | "
            f"{row.agreement:.1%} "
            f"({row.agreement_ci[0]:.1%}–{row.agreement_ci[1]:.1%}) | "
            f"{row.fixed} / {row.broken} | "
            f"{row.mcnemar_p:.4f} | "
            f"{row.kappa:.3f} |"
        )
    return "\n".join(lines)


def render_json(rows: list[PairedStats]) -> str:
    return json.dumps(
        [
            {
                "model": row.model,
                "attempted": row.attempted,
                "correct": row.correct,
                "accuracy": row.accuracy,
                "accuracy_ci95": row.accuracy_ci,
                "agreement": row.agreement,
                "agreement_ci95": row.agreement_ci,
                "fixed": row.fixed,
                "broken": row.broken,
                "mcnemar_p": row.mcnemar_p,
                "cohens_kappa": row.kappa,
            }
            for row in rows
        ],
        indent=2,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-dir", type=Path, default=EVAL_DIR)
    parser.add_argument("--baseline", default=BASELINE_NAME)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = collect(args.eval_dir, args.baseline, DEFAULT_MODELS)
    print(render_json(rows) if args.as_json else render_markdown(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
