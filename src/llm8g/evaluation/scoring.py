"""Reusable scoring functions for free-form and multiple-choice evaluation."""

from __future__ import annotations

import re
from typing import Any


def normalize(text: str) -> str:
    value = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    value = value.replace("```json", "").replace("```", "").strip()
    return re.sub(r"\s+", "", value).casefold()


def score(case: dict[str, Any], answer: str) -> bool:
    match = case.get("match", "exact")
    expected = case.get("expected", [])
    normalized = normalize(answer)
    if match == "exact":
        return normalized in {normalize(str(item)) for item in expected}
    if match == "contains":
        return any(normalize(str(item)) in normalized for item in expected)
    if match == "regex":
        return any(re.search(str(item), normalized) is not None for item in expected)
    raise ValueError(f"unknown match mode: {match}")

