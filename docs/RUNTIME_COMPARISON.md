# Runtime comparison: what is measured, what is not

The portfolio target is not "one engine wins". It is the ability to compare
engines under a **fixed protocol** and to state clearly when a comparison is
invalid.

## Status matrix

| Runtime | Status here | Measured result | Comparable to the vLLM row? |
|---|---|---|---|
| **vLLM 0.29.0** | Measured on RTX 5060 8 GB | **326.53 tok/s** at concurrency 4 through the Kubernetes Service; 0/100 errors; latency p50 500.3 ms, p95 513.8 ms. Streaming TTFT p50 **96.1 ms** (port-forward, one pod). | This is the reference row. |
| **vLLM 0.29.0 (WSL2 k3s, GPU-in-K8s)** | Short smoke only | 100 in-cluster requests, 0 errors, **147.17 tok/s**, p95 3019.9 ms; stream TTFT p50 91.8 ms. Host path is 327.51 tok/s / 513 ms. | Functional only; not a parity claim. |
| **TensorRT-LLM** | **Not measured** | No result claimed. | Would be comparable only after the same model, quantization, input/output lengths, concurrency, and GPU are fixed. |
| **Custom CUDA engine** (`qwen3.5-fp8-cuda`) | Measured in a different repository | **54 tok/s** single-stream, hand-written FP8 kernels. | **No.** Different engine, different batching, different prompt/output protocol. |

## TensorRT-LLM feasibility check (2026-10-21)

A same-model TensorRT-LLM benchmark is not currently possible on this host
without an unsupported build:

- PyPI `tensorrt-llm==1.2.1` requires Python 3.10/3.12, CUDA 13.1,
  TensorRT 10.14.1, and `torch>=2.9.1,<=2.10.0a0`; the recorded vLLM environment
  uses CUDA 13.0 and PyTorch 2.13.0.
- The TensorRT-LLM 1.2.1 support matrix lists **Qwen3**, not **Qwen3.5**, and
  its hardware table does not list the RTX 5060 / SM120 consumer GPU.
- Installing the package and forcing the Qwen3.5 hybrid architecture through an
  unsupported path would not produce a result comparable to the vLLM row.

The correct status remains **not measured**. The harness is ready; the blocker
is supported model/GPU coverage plus a matching CUDA/PyTorch environment, not a
missing benchmark script.

## Why TensorRT-LLM is not in the table

This host is a single RTX 5060 (8 GB) behind Windows/WSL2. A credible
TensorRT-LLM number would require:

1. a TensorRT-LLM build that supports this GPU architecture and the Qwen3.5
   model family;
2. an INT4-AWQ (or FP8) engine built from the same checkpoint;
3. the same `max_model_len`, `max_num_seqs`, prompt length, output length, and
   temperature as the vLLM run;
4. the same client-side measurement of TTFT, TPOT, end-to-end latency, and
   errors.

None of those were completed in this verification run, so the honest status is
"harness ready, result absent". The repository contains a reusable load
generator ([`benchmark/k8s_load_test.py`](../benchmark/k8s_load_test.py)) and
the existing direct OpenAI-compatible load script
([`real_chat_load.py`](../real_chat_load.py)); the next step is to point them at
a TensorRT-LLM OpenAI-compatible server and record the same fields.

## Why the 54 tok/s custom-CUDA number is not a competitor row

The `54 tok/s` figure comes from
[`qwen3.5-fp8-cuda`](https://github.com/francisown/qwen3.5-fp8-cuda), a
from-scratch single-stream engine with hand-written fused kernels. The vLLM
number above is a **batched service** at concurrency 4, measured through a
FastAPI gateway and a Kubernetes Service. Putting them in one column would
compare:

- single-stream vs batched;
- a custom request loop vs an OpenAI-compatible serving stack;
- different prompt/output token budgets;
- different measurement points (engine loop vs gateway + network).

The correct statement is:

> The custom engine demonstrates kernel-level understanding. vLLM demonstrates
> delivery and serving engineering. They are complementary evidence, not two
> points on the same benchmark curve.

## Fixed protocol used for the vLLM row

| Field | Value |
|---|---|
| Model | `Qwen3.5-4B-INT4-AWQ-self` |
| Runtime | vLLM 0.29.0 |
| GPU | NVIDIA RTX 5060, 8,151 MiB |
| Max model length | 2,048 |
| Max sequences | 8 |
| GPU memory utilization | 0.78 |
| Prefix caching / chunked prefill | enabled |
| Prompt | "Explain in one sentence why KV cache matters." |
| Max output tokens | 64 (service load) / 32 (kill-under-load) |
| Temperature | 0 |
| Thinking | disabled |
| Concurrency | 4 |
| Repetitions | 1 run per configuration; results are indicative, not a confidence interval |

## How to add a runtime

1. Serve the same checkpoint behind an OpenAI-compatible `/v1/chat/completions`
   endpoint.
2. Record model, runtime version, GPU, driver, CUDA, quantization, max model
   length, max sequences, prompt/output lengths, temperature, and git revision.
3. Run the same client with warmup and at least 3 repetitions.
4. Report TTFT, TPOT, end-to-end p50/p95, throughput, error rate, GPU memory,
   and cost assumptions separately.
5. If any of those fields differ, mark the row **not comparable** instead of
   putting it in the same table without a caveat.
