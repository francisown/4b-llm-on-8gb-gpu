"""Run the deterministic, no-GPU verification path for the repository.

This command deliberately excludes online smoke tests and model-dependent
benchmarks. Those checks need a running vLLM service, model weights, or the
external C-Eval archive and are documented separately.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run(label: str, command: list[str], *, cwd: Path = PROJECT_ROOT) -> None:
    print(f"\n== {label} ==")
    print("$", " ".join(command))
    completed = subprocess.run(command, cwd=cwd, check=False)
    if completed.returncode:
        raise SystemExit(f"{label} failed with exit code {completed.returncode}")


def validate_layout() -> None:
    required = [
        "gateway/gateway.py",
        "gateway/requirements-dev.txt",
        "pyproject.toml",
        "src/llm8g/serving/http.py",
        "src/llm8g/serving/service.py",
        "tests/test_gateway_http.py",
        "docs/ARCHITECTURE.md",
        "k8s/kustomization.yaml",
        "README.md",
    ]
    missing = [path for path in required if not (PROJECT_ROOT / path).is_file()]
    if missing:
        raise SystemExit("Missing required repository files: " + ", ".join(missing))


def main() -> None:
    validate_layout()
    run(
        "deterministic unit and HTTP contract tests",
        [sys.executable, "-m", "pytest", "-q", "tests"],
    )
    run(
        "Python syntax check",
        [sys.executable, "-m", "compileall", "-q", "gateway", "src", "tools", "tests"],
    )
    print("\nLocal verification passed.")


if __name__ == "__main__":
    main()
