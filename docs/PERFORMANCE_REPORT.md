# Performance report

All numbers below describe the current serving tree and its evidence.
The clean branch intentionally does not carry historical experiment data.

## Environment

| Item | Value |
|---|---|
| GPU | NVIDIA RTX 5060, 8,151 MiB |
| Model | Qwen3.5-4B-INT4-AWQ-self-v1 |
| Runtime | vLLM 0.29.0 |
| Host | Windows + WSL2 Ubuntu 22.04 |
| Gateway | `ai-inference-gateway:stable` |
| Soak client | `benchmark/soak_test.py`, c=4, 32 output tokens |

## Gateway soak

| Run | Requests | Errors | rps | p50 | p95 | p99 |
|---|---:|---:|---:|---:|---:|---:|
| 2 hours, telemetry | **69,687** | **0** | **9.68** | 413.17 ms | **445.26 ms** | **458.04 ms** |
| 10 minutes | **6,212** | **0** | **10.35** | 384.4 ms | 397.15 ms | 418.05 ms |

2-hour telemetry:

- max active: **4**
- max waiting: **1**
- GPU memory: **6,993–7,326 MB**
- GPU utilization: **58–98%**
- after drain: `active=0`, `waiting=0`
- `/health` before/after: `vllm: ok`

Interpretation: the gateway did not build a persistent queue; GPU utilization
was near saturation for most of the run, and GPU memory stayed in a narrow
6.99–7.33 GiB band. The 445 ms p95 is therefore primarily model/GPU-bound, not
gateway admission-bound.

Evidence:

- [`soak-c4-7200s-telemetry.json`](../benchmark/results/soak-c4-7200s-telemetry.json)
- [`soak-c4-600s-metrics-final.json`](../benchmark/results/soak-c4-600s-metrics-final.json)

## Direct vLLM benchmark

Protocol: 16 prompts, 256 input / 128 output, temperature 0, compiled, warmups.

| Concurrency | Output tok/s | TTFT p50 | TPOT p50 |
|---:|---:|---:|---:|
| 1 | **95.55** | 77.03 ms | 9.94 ms |
| 4 | **309.55** | 271.66 ms | 10.88 ms |

This is a microbenchmark, not a capacity plan. It uses the same INT4 checkpoint
as the gateway soak but bypasses the gateway.

Evidence: [`r3-c1`](../benchmark/results/int4-r3-c1.json), [`r3-c4`](../benchmark/results/int4-r3-c4.json).

## Quality

| Check | Result |
|---|---|
| C-Eval 200 questions | **142/200 (71.0%)** |
| Per-question agreement with earlier INT4 v1 report | **99.5%** |
| 32-case quant-quality smoke | **25/32 (78.1%)**, strict = relaxed |

Evidence:

- [`int4-ceval-val-200.json`](../benchmark/eval/int4-ceval-val-200.json)
- [`int4-quant-quality.json`](../benchmark/eval/int4-quant-quality.json)

## Reproducibility

- `gateway/requirements-image.lock.txt` pins the image dependency set;
- Dockerfile installs the lock, then the package with `--no-deps`;
- K8s local overlay pins the locally built digest;
- the image has not been published to GHCR yet.

## Limits

- one GPU, one vLLM version, one model;
- 16-prompt direct benchmark;
- 200-question C-Eval set;
- HPA/TLS use mock vLLM, not the 4B model;
- no TensorRT-LLM comparison.
