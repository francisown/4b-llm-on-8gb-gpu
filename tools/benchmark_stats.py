#!/usr/bin/env python3
"""Compatibility CLI for :mod:`llm8g.benchmarking.stats`."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from llm8g.benchmarking.stats import (  # noqa: E402
    load_runs,
    main,
    mean_ci,
    summarize,
)

__all__ = ["load_runs", "main", "mean_ci", "summarize"]


if __name__ == "__main__":
    raise SystemExit(main())
