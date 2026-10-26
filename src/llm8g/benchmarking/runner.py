"""Protocol-bound benchmark result loading and aggregation.

The shell scripts still drive vLLM; this module is the small, deterministic
seam that validates a result belongs to one protocol and computes a summary.
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import fmean
from typing import Any

from .protocol import BenchmarkProtocol, BenchmarkResult


def protocol_from_mapping(raw: dict[str, Any]) -> BenchmarkProtocol:
    fields = BenchmarkProtocol.__dataclass_fields__
    missing = [name for name in fields if name not in raw]
    if missing:
        raise ValueError(f"protocol is missing fields: {', '.join(missing)}")
    return BenchmarkProtocol(**{name: raw[name] for name in fields})


def load_protocol(path: Path) -> BenchmarkProtocol:
    return protocol_from_mapping(json.loads(path.read_text(encoding="utf-8")))


def result_from_mapping(
    raw: dict[str, Any],
    *,
    protocol: BenchmarkProtocol | None = None,
    raw_path: str | None = None,
) -> BenchmarkResult:
    resolved = protocol
    if resolved is None:
        resolved = protocol_from_mapping(raw["protocol"])
    required = ("throughput_tokens_per_second", "ttft_p50_seconds", "tpot_p50_seconds")
    missing = [name for name in required if name not in raw]
    if missing:
        raise ValueError(f"result is missing fields: {', '.join(missing)}")
    return BenchmarkResult(
        protocol=resolved,
        throughput_tokens_per_second=float(raw["throughput_tokens_per_second"]),
        ttft_p50_seconds=(
            None
            if raw.get("ttft_p50_seconds") is None
            else float(raw["ttft_p50_seconds"])
        ),
        tpot_p50_seconds=(
            None
            if raw.get("tpot_p50_seconds") is None
            else float(raw["tpot_p50_seconds"])
        ),
        error_rate=float(raw.get("error_rate", 0.0)),
        raw_path=raw_path or str(raw.get("raw_path", "")),
        metadata=dict(raw.get("metadata", {})),
    )


def load_result(path: Path, *, protocol: BenchmarkProtocol | None = None) -> BenchmarkResult:
    return result_from_mapping(
        json.loads(path.read_text(encoding="utf-8")),
        protocol=protocol,
        raw_path=str(path),
    )


def summarize(results: list[BenchmarkResult]) -> dict[str, Any]:
    if not results:
        raise ValueError("at least one benchmark result is required")
    protocols = {result.protocol for result in results}
    if len(protocols) != 1:
        raise ValueError("benchmark results use different protocols and cannot be merged")
    protocol = results[0].protocol
    throughputs = [result.throughput_tokens_per_second for result in results]
    ttfts = [
        result.ttft_p50_seconds
        for result in results
        if result.ttft_p50_seconds is not None
    ]
    tpots = [
        result.tpot_p50_seconds
        for result in results
        if result.tpot_p50_seconds is not None
    ]
    return {
        "protocol": protocol,
        "runs": len(results),
        "throughput_mean": fmean(throughputs),
        "throughput_min": min(throughputs),
        "throughput_max": max(throughputs),
        "ttft_p50_mean": fmean(ttfts) if ttfts else None,
        "tpot_p50_mean": fmean(tpots) if tpots else None,
        "error_rate_max": max(result.error_rate for result in results),
    }


def load_results(directory: Path, pattern: str = "*.json") -> list[BenchmarkResult]:
    return [load_result(path) for path in sorted(directory.glob(pattern))]
