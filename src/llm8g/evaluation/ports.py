"""Evaluation ports."""

from __future__ import annotations

from typing import Protocol

from .models import Case


class ModelRunner(Protocol):
    def run(self, case: Case) -> tuple[str, float | None, dict[str, int]]:
        """Return raw answer, latency in seconds, and token usage."""


class PredictionParser(Protocol):
    def __call__(self, answer: str) -> object:
        """Convert raw model output into a comparable prediction."""


class Scorer(Protocol):
    def __call__(self, case: Case, prediction: object) -> bool:
        """Return whether a parsed prediction is correct."""

