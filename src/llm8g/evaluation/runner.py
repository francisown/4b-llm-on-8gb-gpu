"""The evaluation orchestration module."""

from __future__ import annotations

from collections.abc import Iterable
import hashlib
import json
from pathlib import Path
from typing import Callable

from .models import Case, CaseResult, EvaluationReport
from .ports import ModelRunner


def cases_digest(cases: Iterable[Case]) -> str:
    payload = [
        {
            "case_id": case.case_id,
            "prompt": case.prompt,
            "expected": case.expected,
            "metadata": case.metadata,
        }
        for case in cases
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class Evaluator:
    """Run a fixed manifest against an injected model runner."""

    def __init__(
        self,
        runner: ModelRunner,
        *,
        parser: Callable[[str], object] = lambda answer: answer,
        scorer: Callable[[Case, object], bool] = (
            lambda case, prediction: prediction == case.expected
        ),
    ) -> None:
        self.runner = runner
        self.parser = parser
        self.scorer = scorer

    def run(
        self,
        cases: list[Case],
        *,
        label: str,
        model: str,
        resume: EvaluationReport | None = None,
    ) -> EvaluationReport:
        report = resume or EvaluationReport(
            label=label,
            model=model,
            cases_sha256=cases_digest(cases),
        )
        if report.cases_sha256 != cases_digest(cases):
            raise ValueError("existing report uses a different case manifest")
        completed = {result.case_id for result in report.results}
        for case in cases:
            if case.case_id in completed:
                continue
            raw_answer, latency, usage = self.runner.run(case)
            prediction = self.parser(raw_answer)
            report.results.append(
                CaseResult(
                    case_id=case.case_id,
                    expected=case.expected,
                    prediction=prediction,
                    correct=self.scorer(case, prediction),
                    raw_answer=raw_answer,
                    latency_seconds=latency,
                    usage=usage,
                )
            )
        return report

    @staticmethod
    def save(report: EvaluationReport, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

