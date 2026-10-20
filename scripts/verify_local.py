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
        "gateway/test_gateway.py",
        "gateway/requirements-dev.txt",
        "k8s/kustomization.yaml",
        "README.md",
    ]
    missing = [path for path in required if not (PROJECT_ROOT / path).is_file()]
    if missing:
        raise SystemExit("Missing required repository files: " + ", ".join(missing))


def main() -> None:
    validate_layout()
    run(
        "root deterministic unit tests",
        [sys.executable, "-m", "unittest", "tests.test_cost_calculator"],
    )
    run(
        "gateway offline tests",
        [sys.executable, "-m", "pytest", "-q"],
        cwd=PROJECT_ROOT / "gateway",
    )
    run(
        "Python syntax check",
        [sys.executable, "-m", "compileall", "-q", "gateway", "tools", "tests"],
    )
    print("\nLocal verification passed.")


if __name__ == "__main__":
    main()
