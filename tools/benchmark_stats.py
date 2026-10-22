#!/usr/bin/env python3
"""Summarize the three-run vLLM quantization benchmark with confidence intervals.

The raw ``rbq-*`` files use 16 prompts per run. That is enough for a paired
microbenchmark but not for a capacity plan. This tool makes the uncertainty
explicit and flags the raw ``max_concurrent_requests`` field when it disagrees
with the requested concurrency.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any


RESULTS = Path("benchmark/results")
MODELS = (
    ("Third-party FP8", "third-fp8"),
    ("FP8 v3", "self-fp8v3"),
    ("INT4-AWQ", "int4awq"),
)
# 95% two-sided t critical value for n=3.
T_CRITICAL_N3 = 4.302652729911275


def mean_ci(values: list[float]) -> tuple[float, float, float]:
    mean = statistics.fmean(values)
    if len(values) < 2:
        return mean, mean, mean
    standard_error = statistics.stdev(values) / math.sqrt(len(values))
    margin = T_CRITICAL_N3 * standard_error
    return mean, mean - margin, mean + margin


def load_runs(prefix: str, concurrency: int) -> list[dict[str, Any]]:
    runs = []
    for index in (1, 2, 3):
        path = RESULTS / f"rbq-{prefix}-r{index}-c{concurrency}.json"
        runs.append(json.loads(path.read_text(encoding="utf-8-sig")))
    return runs


def summarize(prefix: str, concurrency: int) -> dict[str, Any]:
    runs = load_runs(prefix, concurrency)
    throughputs = [float(run["output_throughput"]) for run in runs]
    ttfts = [float(run["p50_ttft_ms"]) for run in runs]
    tpots = [float(run["p50_tpot_ms"]) for run in runs]
    throughput_mean, throughput_low, throughput_high = mean_ci(throughputs)
    requested = int(runs[0]["max_concurrency"])
    observed = [int(run.get("max_concurrent_requests") or 0) for run in runs]
    return {
        "concurrency": concurrency,
        "runs": len(runs),
        "prompts_per_run": int(runs[0]["num_prompts"]),
        "throughput_mean": throughput_mean,
        "throughput_ci95": [throughput_low, throughput_high],
        "throughput_range_pct": (
            (max(throughputs) - min(throughputs)) / throughput_mean * 100
            if throughput_mean
            else 0.0
        ),
        "ttft_p50_mean": statistics.fmean(ttfts),
        "tpot_p50_mean": statistics.fmean(tpots),
        "requested_max_concurrency": requested,
        "observed_max_concurrent_requests": observed,
        "concurrency_field_matches": all(value == requested for value in observed),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args()


def main() -> int:
    rows = []
    for label, prefix in MODELS:
        for concurrency in (1, 4):
            row = summarize(prefix, concurrency)
            row["model"] = label
            rows.append(row)
    if parse_args().as_json:
        print(json.dumps(rows, indent=2))
        return 0
    print(
        "| Model | c | Prompts | Output tok/s (mean, 95% CI) | Range | "
        "TTFT p50 | TPOT p50 | max_concurrent |"
    )
    print("|---|---:|---:|---:|---:|---:|---:|---|")
    for row in rows:
        low, high = row["throughput_ci95"]
        observed = ",".join(str(value) for value in row["observed_max_concurrent_requests"])
        print(
            f"| {row['model']} | {row['concurrency']} | {row['prompts_per_run']} | "
            f"{row['throughput_mean']:.2f} ({low:.2f}–{high:.2f}) | "
            f"{row['throughput_range_pct']:.2f}% | "
            f"{row['ttft_p50_mean']:.2f} ms | {row['tpot_p50_mean']:.2f} ms | "
            f"{observed} (requested {row['requested_max_concurrency']}) |"
        )
        if not row["concurrency_field_matches"]:
            print(
                f"> note: {row['model']} c={row['concurrency']} reports "
                "`max_concurrent_requests` 2x the requested value; investigate "
                "the benchmark client/warmup accounting before quoting it.",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
