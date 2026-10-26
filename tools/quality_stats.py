#!/usr/bin/env python3
"""Compatibility CLI for :mod:`llm8g.evaluation.stats`."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from llm8g.evaluation.stats import (  # noqa: E402
    PairedStats,
    cohens_kappa,
    collect,
    exact_binomial_two_sided,
    main,
    paired_stats,
    wilson_interval,
)

__all__ = [
    "PairedStats",
    "cohens_kappa",
    "collect",
    "exact_binomial_two_sided",
    "main",
    "paired_stats",
    "wilson_interval",
]


if __name__ == "__main__":
    raise SystemExit(main())
