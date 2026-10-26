"""Compatibility CLI for :mod:`llm8g.quantization.fp8`."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from llm8g.quantization.fp8 import *  # noqa: F401,F403,E402
from llm8g.quantization.fp8 import main  # noqa: E402


if __name__ == "__main__":
    main()

