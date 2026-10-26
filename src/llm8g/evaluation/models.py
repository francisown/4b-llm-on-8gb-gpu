"""Transport-neutral evaluation records."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Case:
    case_id: str
    prompt: str
    expected: Any
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    expected: Any
    prediction: Any
    correct: bool
    raw_answer: str
    latency_seconds: float | None = None
    usage: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EvaluationReport:
    label: str
    model: str
    cases_sha256: str
    results: list[CaseResult] = field(default_factory=list)
    schema_version: int = 1

    def summary(self) -> dict[str, Any]:
        attempted = len(self.results)
        correct = sum(result.correct for result in self.results)
        valid = sum(result.prediction is not None for result in self.results)
        latencies = [
            result.latency_seconds
            for result in self.results
            if result.latency_seconds is not None
        ]
        return {
            "attempted": attempted,
            "correct": correct,
            "accuracy": correct / attempted if attempted else 0.0,
            "valid_predictions": valid,
            "invalid_prediction_rate": (attempted - valid) / attempted if attempted else 0.0,
            "mean_latency_seconds": sum(latencies) / len(latencies) if latencies else 0.0,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "label": self.label,
            "model": self.model,
            "cases_sha256": self.cases_sha256,
            "results": [result.as_dict() for result in self.results],
            "summary": self.summary(),
        }

