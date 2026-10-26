"""Dataset manifests, model runners and evaluation reports."""

from .models import Case, CaseResult, EvaluationReport
from .runner import Evaluator
from .stats import PairedStats, cohens_kappa, paired_stats, wilson_interval
from .ceval import build_prompt, parse_prediction, select_stratified_cases
from .quant_quality import Case as QuantQualityCase, CASES as QUANT_QUALITY_CASES

__all__ = [
    "Case",
    "CaseResult",
    "EvaluationReport",
    "Evaluator",
    "PairedStats",
    "cohens_kappa",
    "paired_stats",
    "wilson_interval",
    "build_prompt",
    "parse_prediction",
    "select_stratified_cases",
    "QuantQualityCase",
    "QUANT_QUALITY_CASES",
]

