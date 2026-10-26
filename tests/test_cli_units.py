from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from llm8g.benchmarking import cost
from llm8g.benchmarking.cost import (
    build_parser,
    calculate,
    local_hourly_cost,
    throughput_from_benchmark,
)
from llm8g.benchmarking.stats import mean_ci
from llm8g.quantization.fp8 import copy_supporting_files as copy_fp8_files
from llm8g.quantization import fp8
from llm8g.quantization.int4_awq import (
    is_dev_csv,
    row_to_text,
    subject_from_name,
)


def test_local_hourly_cost_and_benchmark_loader(tmp_path: Path) -> None:
    cost = local_hourly_cost(
        hardware_price=2000,
        lifetime_years=3,
        utilization=0.5,
        power_watts=150,
        electricity_price_per_kwh=0.2,
    )
    assert cost["total_per_active_hour"] > cost["amortization_per_active_hour"]
    assert cost["electricity_per_active_hour"] == pytest.approx(0.03)

    path = tmp_path / "bench.json"
    path.write_text(json.dumps({"output_throughput": 123.5}), encoding="utf-8")
    assert throughput_from_benchmark(path, "output_throughput") == 123.5
    with pytest.raises(ValueError, match="not found"):
        throughput_from_benchmark(path, "missing")


def test_cost_cli_calculation() -> None:
    args = build_parser().parse_args(
        [
            "--tokens-per-second",
            "100",
            "--hardware-price",
            "2000",
            "--lifetime-years",
            "3",
            "--utilization",
            "0.5",
            "--power-watts",
            "150",
            "--electricity-price-per-kwh",
            "0.2",
        ]
    )
    result = calculate(args)
    assert result["tokens_per_hour"] == 360_000
    assert result["cost_breakdown"]["total_per_active_hour"] > 0


def test_mean_ci_edges() -> None:
    assert mean_ci([5.0]) == (5.0, 5.0, 5.0)
    mean, low, high = mean_ci([1.0, 2.0, 3.0])
    assert mean == 2.0
    assert low < mean < high


def test_int4_calibration_helpers() -> None:
    assert is_dev_csv("dev/data.csv")
    assert not is_dev_csv("math/val.csv")
    assert subject_from_name("math_dev.csv") == "math"
    text = row_to_text(
        "math",
        {
            "question": "1+1?",
            "A": "1",
            "B": "2",
            "C": "3",
            "D": "4",
            "answer": "B",
            "explanation": "two",
        },
    )
    assert "科目：math" in text
    assert "答案：B" in text


def test_supporting_file_copy(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    source.mkdir()
    output.mkdir()
    (source / "config.json").write_text("{}", encoding="utf-8")
    (source / "tokenizer.json").write_text("{}", encoding="utf-8")
    (source / "model.safetensors").write_text("weights", encoding="utf-8")
    copy_fp8_files(source, output)
    assert (output / "tokenizer.json").is_file()
    assert not (output / "config.json").exists()
    assert not (output / "model.safetensors").exists()

def test_cost_cli(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "cost",
            "--tokens-per-second",
            "100",
            "--hardware-price",
            "2000",
            "--lifetime-years",
            "3",
            "--utilization",
            "0.5",
            "--power-watts",
            "150",
            "--electricity-price-per-kwh",
            "0.2",
        ],
    )
    assert cost.cli() == 0
    assert "Cost per 1M tokens" in capsys.readouterr().out

def test_fp8_main_with_fake_model_free_ptq(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "config.json").write_text("{}", encoding="utf-8")
    (source / "tokenizer.json").write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    calls: list[dict[str, object]] = []

    def fake(**kwargs):
        calls.append(kwargs)
        output.mkdir()

    monkeypatch.setitem(
        sys.modules,
        "llmcompressor",
        types.SimpleNamespace(model_free_ptq=fake),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quantize_fp8_block.py",
            "--model",
            str(source),
            "--output",
            str(output),
            "--device",
            "cpu",
        ],
    )
    fp8.main()
    assert calls and calls[0]["scheme"] == "FP8_BLOCK"
    assert (output / "tokenizer.json").is_file()


def test_cli_serve_entrypoint(monkeypatch) -> None:
    from llm8g import cli

    invoked = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: invoked.append((app, kwargs)))
    assert cli.main(["serve", "--host", "127.0.0.1", "--port", "9999"]) == 0
    assert invoked
