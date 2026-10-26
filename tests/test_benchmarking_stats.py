from __future__ import annotations

import json
from pathlib import Path

from llm8g.benchmarking import stats


def test_stats_loads_and_summarizes_three_runs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(stats, "RESULTS", tmp_path)
    for index, throughput in enumerate((300.0, 310.0, 320.0), 1):
        path = tmp_path / f"rbq-demo-r{index}-c4.json"
        path.write_text(
            json.dumps(
                {
                    "output_throughput": throughput,
                    "p50_ttft_ms": 250.0 + index,
                    "p50_tpot_ms": 10.0,
                    "max_concurrency": 4,
                    "num_prompts": 16,
                    "max_concurrent_requests": 4,
                }
            ),
            encoding="utf-8",
        )

    runs = stats.load_runs("demo", 4)
    assert len(runs) == 3
    summary = stats.summarize("demo", 4)
    assert summary["throughput_mean"] == 310.0
    assert summary["concurrency_field_matches"] is True
    assert summary["prompts_per_run"] == 16

def test_stats_main_renders_table(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(stats, "RESULTS", tmp_path)
    monkeypatch.setattr(stats, "MODELS", (("Demo", "demo"),))
    monkeypatch.setattr("sys.argv", ["benchmark_stats"])
    for concurrency in (1, 4):
        for index in (1, 2, 3):
            (tmp_path / f"rbq-demo-r{index}-c{concurrency}.json").write_text(
                json.dumps(
                    {
                        "output_throughput": 100.0 + index,
                        "p50_ttft_ms": 10.0,
                        "p50_tpot_ms": 5.0,
                        "max_concurrency": concurrency,
                        "num_prompts": 16,
                        "max_concurrent_requests": concurrency,
                    }
                ),
                encoding="utf-8",
            )
    assert stats.main() == 0
    assert "Demo" in capsys.readouterr().out
