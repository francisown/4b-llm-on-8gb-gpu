from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pytest

from llm8g.evaluation.ceval import (
    build_prompt,
    load_ceval_split,
    select_stratified_cases,
    parse_prediction,
    prepare_manifest,
    sha256_file,
    sha256_json,
    summarize,
)
from llm8g.evaluation import ceval, http as eval_http, quant_quality
from llm8g.evaluation.reporting import load_json
from llm8g.evaluation.quant_quality import (
    Case,
    long_context_case,
    normalized,
    percentile,
    save_report,
    score,
)

CEVAL_ZIP = Path(
    os.environ.get("CEVAL_ZIP", "/mnt/e/AI-Inference-Lab/datasets/ceval.zip")
)


def test_scoring_and_percentile() -> None:
    exact = Case("exact", "test", "prompt", ("42",), True)
    assert score(exact, " 42 ") == (True, True)
    relaxed = Case("relaxed", "test", "prompt", ("AX-19",), False)
    assert score(relaxed, "the key is AX-19") == (False, True)
    assert normalized("```json\n{\"a\": 1}\n```") == '{"a":1}'
    assert percentile([1.0, 2.0, 3.0], 0.5) == 2.0
    assert long_context_case("long", 10, "9").answers == ("9",)


def test_save_report_and_summary(tmp_path: Path) -> None:
    results = [
        {
            "case_id": "a",
            "category": "math",
            "strict_pass": True,
            "relaxed_pass": True,
            "latency_seconds": 0.1,
        },
        {
            "case_id": "b",
            "category": "math",
            "strict_pass": False,
            "relaxed_pass": True,
            "latency_seconds": 0.3,
        },
    ]
    output = tmp_path / "report.json"
    save_report(
        label="test",
        model="model",
        backend="http://localhost",
        max_tokens=8,
        started=0.0,
        results=results,
        output=output,
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"]["cases"] == 2
    assert report["summary"]["strict_pass"] == 1
    assert report["summary"]["relaxed_pass"] == 2


def test_ceval_prompt_parser_hash_and_summary(tmp_path: Path) -> None:
    case = {
        "subject": "math",
        "question": "1+1?",
        "A": "1",
        "B": "2",
        "C": "3",
        "D": "4",
        "answer": "B",
    }
    prompt = build_prompt(case)
    assert "科目：math" in prompt
    assert "答案：" in prompt
    assert parse_prediction("B") == "B"
    assert parse_prediction("答案是 C") == "C"
    assert parse_prediction("no answer") is None

    file = tmp_path / "data.txt"
    file.write_text("data", encoding="utf-8")
    assert sha256_file(file) == sha256_file(file)
    assert sha256_json({"a": 1}) == sha256_json({"a": 1})

    summary = summarize(
        [
            {
                "subject": "math",
                "prediction": "B",
                "correct": True,
                "latency_seconds": 0.1,
            },
            {
                "subject": "math",
                "prediction": None,
                "correct": False,
                "latency_seconds": 0.2,
            },
        ]
    )
    assert summary["attempted"] == 2
    assert summary["valid_predictions"] == 1
    assert summary["correct"] == 1
    assert summary["by_subject"]["math"]["attempted"] == 2


@pytest.mark.skipif(not CEVAL_ZIP.is_file(), reason="C-Eval archive is not present")
def test_prepare_manifest_from_archive(tmp_path: Path) -> None:
    output = tmp_path / "ceval.json"
    manifest = prepare_manifest(CEVAL_ZIP, output, samples=52, seed=7)
    assert output.is_file()
    assert manifest["samples"] == 52
    assert len(manifest["cases"]) == 52

@pytest.mark.skipif(not CEVAL_ZIP.is_file(), reason="C-Eval archive is not present")
def test_load_and_stratify_ceval() -> None:
    grouped = load_ceval_split(CEVAL_ZIP, "val")
    cases = select_stratified_cases(grouped, samples=60, seed=3)
    assert len(cases) == 60
    assert len({case["subject"] for case in cases}) >= 1

def test_ceval_run_with_fake_transport(tmp_path: Path, monkeypatch, capsys) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "cases_sha256": "abc",
                "cases": [
                    {
                        "case_id": "q1",
                        "subject": "math",
                        "question": "1+1?",
                        "A": "1",
                        "B": "2",
                        "C": "3",
                        "D": "4",
                        "answer": "B",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        ceval,
        "request_chat",
        lambda **_: ("B", {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, 0.01),
    )
    output = tmp_path / "report.json"
    args = argparse.Namespace(
        manifest=manifest,
        base_url="http://localhost/v1",
        model="model",
        label="test",
        output=output,
        timeout=1.0,
        limit=1,
        resume=False,
    )
    ceval.run_evaluation(args)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"]["correct"] == 1
    assert "Saved" in capsys.readouterr().out


def test_quant_quality_run_with_fake_transport(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        quant_quality,
        "request_json",
        lambda *_: {
            "choices": [{"message": {"content": "42"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )
    output = tmp_path / "quant.json"
    args = argparse.Namespace(
        base_url="http://localhost/v1",
        model="model",
        label="test",
        output=output,
        max_tokens=8,
        timeout=1.0,
    )
    quant_quality.run(args)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"]["cases"] == len(quant_quality.CASES)
    assert "Saved" in capsys.readouterr().out

class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self.payload


def test_evaluation_http_helpers(monkeypatch) -> None:
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        if request.full_url.endswith("/chat/completions"):
            return _FakeResponse(
                json.dumps(
                    {
                        "choices": [{"message": {"content": "A"}}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    }
                ).encode("utf-8")
            )
        return _FakeResponse(b'{"ok": true}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert eval_http.post_json("http://example.test", {"a": 1}, 1.0) == {"ok": True}
    answer, usage, latency = eval_http.chat_completion(
        base_url="http://example.test/v1",
        model="model",
        prompt="hello",
        timeout=1.0,
    )
    assert answer == "A"
    assert usage["total_tokens"] == 2
    assert latency >= 0
    assert len(calls) == 2

def test_reporting_load_json(tmp_path: Path) -> None:
    path = tmp_path / "value.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    assert load_json(path) == {"a": 1}
