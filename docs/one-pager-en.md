# One-pager · 8GB LLM inference delivery

**In one sentence.** I built an end-to-end LLM inference delivery pipeline on one RTX 5060 with 8 GB of VRAM — quantization, quality evaluation, scheduling tuning, service packaging, and offline delivery — and kept reproducible raw data at every step.

---

## Three numbers

| | Number | Conditions |
|---|---|---|
| Single-GPU output throughput | **5,693 tok/s** | Qwen3-0.6B, concurrency 64, 256-in / 128-out, 100% success (21.4× from c=1 to c=64) |
| 4B model shrunk to | **3.568 GiB** (59% smaller than BF16) | Self-made W4A16 INT4-AWQ; +43.0% throughput at c=1, +30.0% at c=4 versus third-party FP8 (mean of 3 runs, within-session spread ≤0.6%) |
| Delivery bundle verified on a clean host | **7.49 GiB** | Model, runtime, gateway, Compose, SHA-256 manifests |

> The first row is **Qwen3-0.6B** (chosen because it is small enough to drive the sweep to concurrency 64 without hitting the VRAM ceiling); the other two are **Qwen3.5-4B**. Two different model generations — do not use one to explain the other.

---

## What I did

**1. Quantization.** Two scripts: FP8_BLOCK, and asymmetric W4A16 INT4-AWQ. The AWQ path calibrates on 128 C-Eval `dev` samples, calibrates one decoder layer at a time with CPU offload, stores 200 linear weights as packed INT4, and keeps `lm_head` plus sensitive projections in BF16.

**2. Evaluation.** A frozen 200-question C-Eval `val` set (52 subjects, sample SHA-256 pinned), with the calibration split kept fully disjoint to avoid leakage. Prompts, question order, parsing, and `temperature=0` all held constant.

The finding worth reporting: four models — BF16, third-party FP8, self-made FP8, self-made INT4 — **scored identically at 141/200**. But per-question answer agreement against BF16 was 100% / 96.5% / 98.0% / 87.0%, and INT4 picked a different option on 26 questions.

> An identical total score does not make two models equivalent. The Wilson 95% interval for 200 binary questions is 63.84%–76.39% — nowhere near enough to claim equivalence.

**3. Tuning.** Concurrency sweep to 64; long-context and `max-num-seqs` boundary experiments; prefix-cache cold/hot comparison; chunked-prefill mixed load; MTP-4/MTP-5 versus N-gram speculative decoding. On speculative decoding, MTP-5 lifted c=4 throughput from 104.26 to 351.37 tok/s — **but 8 GB cannot hold long context, high concurrency, CUDA Graph, and aggressive MTP at the same time**, so the stable delivery bundle falls back to a more conservative N-gram configuration.

> The optimal configuration and the shippable configuration are not the same thing. That boundary was measured, not guessed.

**4. Serving and delivery.** A FastAPI gateway with SSE streaming (including TTFT and end-to-end latency), four independent timeout classes, bounded concurrency and queueing with HTTP 429 backpressure, Prometheus metrics, separate `/live` and `/health` probes, single-line JSON logs, and a non-root image. **Fourteen pytest cases that need neither a model nor a GPU**, covering success, validation failure, upstream timeout/disconnect/HTTP error, capacity rejection, queue timeout, connect retry, probe identity, and optional API-key authentication. Optional bearer/`X-API-Key` auth protects chat endpoints; health and metrics stay open for probes and Prometheus.

**5. Deployed and measured (2026-10-21).** A two-replica Kubernetes gateway with readiness/liveness, PDB, zero-downtime rollout, and rollback completed 100 in-cluster requests at 0 errors and 326.53 tok/s; 300 requests during a deliberate pod kill completed at 0 errors. Prometheus scrapes both replicas, and a provisioned Grafana dashboard shows request rate, errors, TTFT, latency, admission control, and upstream health. A 120 s gateway soak completed 2,329 requests with 0 errors; a concurrency-16 backpressure run produced 6,544 clean 429s with 0 other errors. GPU inference still runs outside the cluster; stable in-cluster GPU vLLM was blocked by WSL2/k3s `PLEG` and is not claimed.

---

## Roles this fits

Inference engineering · Model deployment and quantization · AI platform engineering (serving and delivery) · MLOps

---

## Where I won't overclaim

- Every number applies only to this hardware, vLLM 0.29.0, and short-context conditions — not generalizable to other GPUs or long-context workloads.
- The BF16 checkpoint does not fit in 8 GB, so it ran layer-wise on CPU as a quality baseline. **Its latency is not comparable to a GPU-resident vLLM model.**
- A 200-question multiple-choice set only supports "no accuracy difference observed on these 200 questions." Free-form text, code, long context, and domain data all need separate evaluation.
- The cost calculator is a capacity-cost estimate. It excludes network, storage, labour, tax, and redundancy, and is not a cloud API quote.
