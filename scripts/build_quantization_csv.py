#!/usr/bin/env python3
"""Build or check the machine-readable quantization comparison CSV.

The CSV is derived from the frozen C-Eval per-question results and from the
three-run `rbq-*` vLLM benchmark files. Run with ``--check`` in CI to prevent
the table from drifting away from the raw evidence again.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "benchmark" / "eval"
RESULTS_DIR = ROOT / "benchmark" / "results"
OUTPUT = EVAL_DIR / "quantization-final-comparison.csv"

FIELDS = [
    "model",
    "precision",
    "model_size_gib",
    "size_reduction_vs_bf16_pct",
    "ceval_correct",
    "ceval_total",
    "ceval_accuracy_pct",
    "valid_prediction_pct",
    "prediction_agreement_vs_bf16_pct",
    "fixed_bf16_errors",
    "regressed_bf16_correct",
    "c1_output_tps",
    "c1_ttft_p50_ms",
    "c1_tpot_p50_ms",
    "c4_output_tps",
    "c4_ttft_p50_ms",
    "c4_tpot_p50_ms",
    "notes",
]

MODELS = [
    {
        "model": "BF16 reference",
        "precision": "BF16",
        "size": 8.701,
        "reduction": 0.0,
        "quality": "bf16-reference",
        "perf": None,
        "notes": (
            "Quality evaluated with Transformers GPU/CPU layer placement; "
            "checkpoint cannot run as a fully GPU-resident vLLM service on "
            "this 8 GB GPU"
        ),
    },
    {
        "model": "Third-party FP8",
        "precision": "FP8",
        "size": 5.281,
        "reduction": 39.3,
        "quality": "third-party-fp8",
        "perf": "rbq-third-fp8",
        "notes": "Compiled vLLM benchmark",
    },
    {
        "model": "Self FP8 v3",
        "precision": "FP8_BLOCK",
        "size": 5.281,
        "reduction": 39.3,
        "quality": "self-fp8-v3",
        "perf": "rbq-self-fp8v3",
        "notes": "Compiled vLLM benchmark; closest predictions to BF16",
    },
    {
        "model": "Self INT4-AWQ v1",
        "precision": "W4A16 INT4-AWQ",
        "size": 3.568,
        "reduction": 59.0,
        "quality": "self-int4-awq-v1",
        "perf": "rbq-int4awq",
        "notes": (
            "Compiled vLLM benchmark; highest throughput and largest "
            "behavioral change"
        ),
    },
]


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def quality_stats(name: str, baseline: dict[str, dict]) -> tuple[float, ...]:
    report = load_json(EVAL_DIR / f"{name}-ceval-val-200.json")
    summary = report["summary"]
    results = {row["case_id"]: row for row in report["results"]}
    if set(results) != set(baseline):
        raise SystemExit(f"{name}: case IDs do not match the BF16 baseline")
    agreement = sum(
        1 for case_id, row in baseline.items() if results[case_id]["prediction"] == row["prediction"]
    )
    fixed = sum(
        1 for case_id, row in baseline.items() if results[case_id]["correct"] and not row["correct"]
    )
    regressed = sum(
        1 for case_id, row in baseline.items() if not results[case_id]["correct"] and row["correct"]
    )
    attempted = int(summary["attempted"])
    correct = int(summary["correct"])
    valid = int(summary["valid_predictions"])
    return (
        correct,
        attempted,
        round(correct / attempted * 100, 1),
        round(valid / attempted * 100, 1),
        round(agreement / attempted * 100, 1),
        fixed,
        regressed,
    )


def metric_mean(prefix: str, concurrency: int, metric: str) -> float:
    values = []
    for run in (1, 2, 3):
        path = RESULTS_DIR / f"{prefix}-r{run}-c{concurrency}.json"
        values.append(float(load_json(path)[metric]))
    return round(statistics.fmean(values), 2)


def build_rows() -> list[dict[str, str | int | float]]:
    baseline_report = load_json(EVAL_DIR / "bf16-reference-ceval-val-200.json")
    baseline = {row["case_id"]: row for row in baseline_report["results"]}
    baseline_summary = baseline_report["summary"]
    rows: list[dict[str, str | int | float]] = []
    for spec in MODELS:
        if spec["model"] == "BF16 reference":
            quality = (
                int(baseline_summary["correct"]),
                int(baseline_summary["attempted"]),
                70.5,
                100.0,
                100.0,
                0,
                0,
            )
        else:
            quality = quality_stats(spec["quality"], baseline)
        row: dict[str, str | int | float] = {
            "model": spec["model"],
            "precision": spec["precision"],
            "model_size_gib": spec["size"],
            "size_reduction_vs_bf16_pct": spec["reduction"],
            "ceval_correct": quality[0],
            "ceval_total": quality[1],
            "ceval_accuracy_pct": quality[2],
            "valid_prediction_pct": quality[3],
            "prediction_agreement_vs_bf16_pct": quality[4],
            "fixed_bf16_errors": quality[5],
            "regressed_bf16_correct": quality[6],
            "c1_output_tps": "",
            "c1_ttft_p50_ms": "",
            "c1_tpot_p50_ms": "",
            "c4_output_tps": "",
            "c4_ttft_p50_ms": "",
            "c4_tpot_p50_ms": "",
            "notes": spec["notes"],
        }
        if spec["perf"]:
            for concurrency in (1, 4):
                row[f"c{concurrency}_output_tps"] = metric_mean(
                    spec["perf"], concurrency, "output_throughput"
                )
                row[f"c{concurrency}_ttft_p50_ms"] = metric_mean(
                    spec["perf"], concurrency, "p50_ttft_ms"
                )
                row[f"c{concurrency}_tpot_p50_ms"] = metric_mean(
                    spec["perf"], concurrency, "p50_tpot_ms"
                )
        rows.append(row)
    return rows


def render() -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(build_rows())
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the committed CSV differs from the generated table",
    )
    args = parser.parse_args()
    generated = render()
    if args.check:
        if not OUTPUT.exists():
            raise SystemExit(f"missing {OUTPUT}")
        if OUTPUT.read_text(encoding="utf-8") != generated:
            raise SystemExit(
                "quantization-final-comparison.csv is stale; run "
                "python scripts/build_quantization_csv.py"
            )
        print("Quantization CSV matches the raw evidence.")
        return 0
    OUTPUT.write_text(generated, encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
