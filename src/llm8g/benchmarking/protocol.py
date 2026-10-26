"""Benchmark inputs and results with comparability checks."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True, slots=True)
class BenchmarkProtocol:
    name: str
    runtime: str
    runtime_version: str
    model: str
    gpu: str
    input_tokens: int
    output_tokens: int
    concurrency: int
    repetitions: int
    temperature: float = 0.0
    enable_thinking: bool = False

    def __post_init__(self) -> None:
        if self.input_tokens < 1 or self.output_tokens < 1:
            raise ValueError("token counts must be positive")
        if self.concurrency < 1 or self.repetitions < 1:
            raise ValueError("concurrency and repetitions must be positive")

    def comparable_with(self, other: "BenchmarkProtocol") -> bool:
        return self == other


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    protocol: BenchmarkProtocol
    throughput_tokens_per_second: float
    ttft_p50_seconds: float | None
    tpot_p50_seconds: float | None
    error_rate: float
    raw_path: str
    metadata: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["protocol"] = asdict(self.protocol)
        return value

