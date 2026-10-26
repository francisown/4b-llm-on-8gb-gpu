"""Compatibility CLI for :mod:`llm8g.benchmarking.cost`."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from llm8g.benchmarking.cost import (  # noqa: E402
    cli,
    cost_per_million,
    local_hourly_cost,
    tokens_per_hour,
    throughput_from_benchmark,
)

__all__ = [
    "cli",
    "cost_per_million",
    "local_hourly_cost",
    "tokens_per_hour",
    "throughput_from_benchmark",
]


if __name__ == "__main__":
    raise SystemExit(cli())
