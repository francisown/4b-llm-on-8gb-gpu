# Performance report

All numbers below describe the current serving tree and its evidence. Historical
run dumps are not included; the frozen reference files needed for the current
comparisons are kept in `benchmark/eval/`.

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
The current files are **one run per concurrency**, not a repeated measurement.

| Concurrency | Output tok/s | TTFT p50 | TPOT p50 |
|---:|---:|---:|---:|
| 1 | **95.55** | 77.03 ms | 9.94 ms |
| 4 | **309.55** | 271.66 ms | 10.88 ms |

This is a microbenchmark, not a capacity plan. It uses the same INT4 checkpoint
as the gateway soak but bypasses the gateway. The frozen INT4 v1 reference
reported 333.9 tok/s at c=4; the current 309.55 is a single run, so this is not
by itself evidence of a controlled regression. Repeat before making a
regression claim.

Evidence: [`int4-c1`](../benchmark/results/int4-c1.json),
[`int4-c4`](../benchmark/results/int4-c4.json).

## Quality

Current recheck:

| Check | Result |
|---|---|
| C-Eval 200 questions | **142/200 (71.0%)**; Wilson 95% **64.4–76.8%** |
| Current INT4 vs INT4 v1 | **99.5% agreement** (95% Wilson **97.2–99.9%**), **1 fixed / 0 broken**, McNemar p **1.0000**, κ **0.993** |
| 32-case quant-quality smoke | **25/32 (78.1%)**, strict = relaxed |

Evidence:

- [`int4-ceval-val-200.json`](../benchmark/eval/int4-ceval-val-200.json)
- [`int4-vs-v1-agreement.json`](../benchmark/eval/int4-vs-v1-agreement.json)
- [`int4-quant-quality.json`](../benchmark/eval/int4-quant-quality.json)

## Quantization comparison

The BF16, third-party FP8, local FP8 v3 and local INT4 v1 files are frozen
reference baselines. They are retained because the current INT4 result is
compared with INT4 v1, and because the FP8 sizes and BF16 agreement numbers come
from this set.

| Model | Size | C-Eval | Agreement vs BF16 | c=1 tok/s | c=4 tok/s |
|---|---:|---:|---:|---:|---:|
| BF16 reference | 8.701 GiB | 141/200 (70.5%) | 100.0% | — | — |
| Third-party FP8 | 5.281 GiB | 141/200 (70.5%) | 96.5% | 72.02 | 256.83 |
| Local FP8 v3 | 5.281 GiB | 141/200 (70.5%) | 98.0% | 72.76 | 257.33 |
| Local INT4-AWQ v1 | 3.568 GiB | 141/200 (70.5%) | 87.0% | 102.99 | 333.90 |
| Current INT4 recheck | 3.568 GiB | 142/200 (71.0%) | 99.5% vs INT4 v1 | 95.55 | 309.55 |

Reference paired statistics (BF16 baseline):

| Model | Accuracy (95% Wilson) | Agreement with BF16 (95% Wilson) | Fixed / broken | McNemar p | Cohen's κ |
|---|---:|---:|---:|---:|---:|
| Third-party FP8 | 141/200 = 70.5% (63.8–76.4%) | 96.5% (93.0–98.3%) | 3 / 3 | 1.0000 | 0.953 |
| Local FP8 v3 | 141/200 = 70.5% (63.8–76.4%) | 98.0% (95.0–99.2%) | 2 / 2 | 1.0000 | 0.973 |
| Local INT4-AWQ v1 | 141/200 = 70.5% (63.8–76.4%) | 87.0% (81.6–91.0%) | 11 / 11 | 1.0000 | 0.826 |

Evidence: [`quantization-final-comparison.csv`](../benchmark/eval/quantization-final-comparison.csv),
[`int4-vs-v1-agreement.json`](../benchmark/eval/int4-vs-v1-agreement.json).
Regenerate the reference table with `python tools/quality_stats.py`.

## Reproducibility

- `gateway/requirements-image.lock.txt` pins the image dependency set;
- the Dockerfile installs the lock, then the package with `--no-deps`;
- the quantization CLI writes `artifact-manifest.json` into the output directory;
- the local K8s overlay uses the locally built `stable` tag; the GHCR overlay
  uses `latest` after publication;
- the model weights and C-Eval archive are not redistributed; see the
  third-party assets section in the repository README.

## Limits

- one GPU, one vLLM version, one model;
- direct vLLM benchmark is one run per concurrency;
- 16-prompt direct benchmark;
- 200-question C-Eval set;
- HPA/TLS use mock vLLM, not the 4B model;
- FP8 and INT4 v1 rows are frozen reference measurements, not reruns of the
  current tree;
- no TensorRT-LLM comparison.
