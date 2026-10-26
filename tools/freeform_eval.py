#!/usr/bin/env python3
"""Run the small free-form regression set against an OpenAI-compatible endpoint.

This is intentionally not a leaderboard. It checks behavior that the 200-item
A/B/C/D set cannot see: formatting, code execution, long-context retrieval, and
a little reasoning. Scoring is deterministic and dependency-free.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
import urllib.request
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from llm8g.evaluation.scoring import normalize, score  # noqa: F401

__all__ = ["normalize", "score"]



DEFAULT_CASES = Path("benchmark/eval/freeform-cases.json")
DEFAULT_OUTPUT = Path("benchmark/eval/freeform-smoke.json")


def request_answer(base_url: str, model: str, prompt: str, timeout: float) -> tuple[str, float]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 64,
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer EMPTY",
        },
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    latency = time.perf_counter() - started
    return data["choices"][0]["message"]["content"], latency


def run(
    *,
    base_url: str,
    model: str,
    cases_path: Path,
    timeout: float,
) -> dict[str, Any]:
    manifest = json.loads(cases_path.read_text(encoding="utf-8"))
    results = []
    for case in manifest["cases"]:
        answer, latency = request_answer(base_url, model, case["prompt"], timeout)
        results.append(
            {
                "id": case["id"],
                "category": case["category"],
                "expected": case["expected"],
                "answer": answer,
                "passed": score(case, answer),
                "latency_seconds": round(latency, 6),
            }
        )
    passed = sum(row["passed"] for row in results)
    by_category: dict[str, dict[str, int]] = {}
    for row in results:
        bucket = by_category.setdefault(
            row["category"], {"total": 0, "passed": 0}
        )
        bucket["total"] += 1
        bucket["passed"] += int(row["passed"])
    return {
        "schema_version": 1,
        "model": model,
        "base_url": base_url,
        "cases": cases_path.name,
        "passed": passed,
        "total": len(results),
        "accuracy": passed / len(results) if results else 0.0,
        "by_category": by_category,
        "results": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run(
        base_url=args.base_url,
        model=args.model,
        cases_path=args.cases,
        timeout=args.timeout,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"{report['passed']}/{report['total']} = {report['accuracy']:.1%} "
        f"(saved to {args.output})"
    )
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
