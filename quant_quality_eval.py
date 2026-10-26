"""Compatibility CLI for :mod:`llm8g.evaluation.quant_quality`."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from llm8g.evaluation.quant_quality import *  # noqa: F401,F403,E402
from llm8g.evaluation.quant_quality import main  # noqa: E402


if __name__ == "__main__":
    main()

