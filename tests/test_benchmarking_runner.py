from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm8g.benchmarking import (
    BenchmarkProtocol,
    BenchmarkResult,
    load_result,
    load_results,
    protocol_from_mapping,
    summarize,
)


def protocol() -> BenchmarkProtocol:
    return BenchmarkProtocol(
        "p",
        "vllm",
        "0.29.0",
        "model",
        "RTX 5060",
        256,
        128,
        4,
        3,
    )


def result(throughput: float) -> BenchmarkResult:
    return BenchmarkResult(
        protocol=protocol(),
        throughput_tokens_per_second=throughput,
        ttft_p50_seconds=0.25,
        tpot_p50_seconds=0.01,
        error_rate=0.0,
        raw_path="raw.json",
        metadata={},
    )


def test_protocol_mapping_rejects_missing_fields() -> None:
    with pytest.raises(ValueError, match="missing fields"):
        protocol_from_mapping({"name": "p"})


def test_result_loader_and_summary(tmp_path: Path) -> None:
    raw = {
        "protocol": {
            "name": "p",
            "runtime": "vllm",
            "runtime_version": "0.29.0",
            "model": "model",
            "gpu": "RTX 5060",
            "input_tokens": 256,
            "output_tokens": 128,
            "concurrency": 4,
            "repetitions": 3,
            "temperature": 0.0,
            "enable_thinking": False,
        },
        "throughput_tokens_per_second": 300.0,
        "ttft_p50_seconds": 0.25,
        "tpot_p50_seconds": 0.01,
        "error_rate": 0.0,
        "metadata": {"source": "test"},
    }
    path = tmp_path / "run.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    loaded = load_result(path)
    assert loaded.throughput_tokens_per_second == 300.0
    assert loaded.raw_path == str(path)

    summary = summarize([result(300.0), result(320.0)])
    assert summary["runs"] == 2
    assert summary["throughput_mean"] == 310.0
    assert summary["throughput_min"] == 300.0
    assert summary["throughput_max"] == 320.0


def test_summary_refuses_mixed_protocols() -> None:
    other = BenchmarkProtocol(
        "p",
        "vllm",
        "0.29.0",
        "model",
        "RTX 5060",
        256,
        128,
        8,
        3,
    )
    mismatch = BenchmarkResult(
        protocol=other,
        throughput_tokens_per_second=300.0,
        ttft_p50_seconds=0.25,
        tpot_p50_seconds=0.01,
        error_rate=0.0,
        raw_path="raw.json",
        metadata={},
    )
    with pytest.raises(ValueError, match="different protocols"):
        summarize([result(300.0), mismatch])

def test_protocol_validation_and_result_dict() -> None:
    with pytest.raises(ValueError, match="token counts"):
        BenchmarkProtocol("p", "vllm", "1", "m", "gpu", 0, 1, 1, 1)
    with pytest.raises(ValueError, match="concurrency"):
        BenchmarkProtocol("p", "vllm", "1", "m", "gpu", 1, 1, 0, 1)
    value = result(300.0).as_dict()
    assert value["protocol"]["name"] == "p"
    assert value["throughput_tokens_per_second"] == 300.0

def test_load_results_directory(tmp_path: Path) -> None:
    raw = {
        "protocol": {
            "name": "p",
            "runtime": "vllm",
            "runtime_version": "0.29.0",
            "model": "model",
            "gpu": "RTX 5060",
            "input_tokens": 256,
            "output_tokens": 128,
            "concurrency": 4,
            "repetitions": 3,
            "temperature": 0.0,
            "enable_thinking": False,
        },
        "throughput_tokens_per_second": 300.0,
        "ttft_p50_seconds": 0.25,
        "tpot_p50_seconds": 0.01,
        "error_rate": 0.0,
    }
    (tmp_path / "one.json").write_text(json.dumps(raw), encoding="utf-8")
    assert len(load_results(tmp_path, "*.json")) == 1
