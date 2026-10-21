# One-pager · 8GB LLM inference delivery

**In one sentence.** I built an end-to-end LLM inference delivery path on one RTX 5060 with 8 GB of VRAM — quantization, quality evaluation, scheduling tuning, service packaging, and local offline delivery — and kept raw evidence at every step.

---

## Three numbers

| | Number | Conditions |
|---|---|---|
| 4B model shrunk to | **3.568 GiB** (59% smaller than BF16) | Self-made W4A16 INT4-AWQ; 32% smaller than FP8 |
| INT4-AWQ output throughput | **333.90 tok/s** at c=4 | 256-in / 128-out, temperature 0, mean of 3 runs; TTFT p50 251.73 ms |
| Real-vLLM 30-minute soak | **17,609 requests, 0 errors** | c=4, 9.781 req/s, p95 433.79 ms; a separate 2-hour mock-gateway soak handled 140,178 requests |

The quality result is the part worth discussing: BF16, third-party FP8, self-made FP8, and self-made INT4 all scored **141/200** on the frozen C-Eval set, but INT4 agreed with BF16 on only **87.0%** of questions and changed 26 answers. Equal totals do not mean equivalent models. The Wilson 95% interval for 200 questions is 63.84%–76.39%, so this is not an equivalence claim.

A Qwen3-0.6B run (5,693 tok/s at c=64) appears in the appendix of the main README as an engine-batching test load, not as a delivery-model number.

---

## What I did

**1. Quantization.** Two scripts: FP8_BLOCK and asymmetric W4A16 INT4-AWQ. The AWQ path calibrates on 128 C-Eval `dev` samples, calibrates one decoder layer at a time with CPU offload, stores 200 linear weights as packed INT4, and keeps `lm_head` plus sensitive projections in BF16.

**2. Evaluation.** A frozen 200-question C-Eval `val` set (52 subjects, sample SHA-256 pinned), with the calibration split kept disjoint. Prompts, question order, parsing, and `temperature=0` were held constant. Per-question agreement, fixed errors, and regressions are reported alongside accuracy.

**3. Tuning.** Concurrency sweep to 64; long-context and `max-num-seqs` boundary experiments; prefix-cache cold/hot comparison; chunked-prefill mixed load; MTP-4/MTP-5 versus N-gram speculative decoding. MTP-5 lifted c=4 throughput from 104.26 to 351.37 tok/s, **but 8 GB cannot hold long context, high concurrency, CUDA Graph, and aggressive MTP at the same time**, so the stable bundle uses a conservative N-gram configuration.

**4. Serving.** A FastAPI gateway with SSE streaming (TTFT and end-to-end latency), four independent timeout classes, bounded concurrency and queueing with HTTP 429 backpressure, Prometheus metrics, split `/live` and `/health` probes, single-line JSON logs, optional API-key auth, per-identity rate limiting, and a non-root image. **19 pytest cases** need neither a model nor a GPU.

**5. Deployment.** A two-replica Kubernetes gateway with readiness/liveness, PDB, zero-downtime rollout, and rollback completed 100 in-cluster requests at 0 errors and 326.53 tok/s; 300 requests during a deliberate pod kill completed at 0 errors. HPA 2→4→2 was validated separately with CPU metrics and a mock upstream (45 s / 90 s). A later WSL2 k3s smoke test ran vLLM inside the cluster with `nvidia.com/gpu: 1` and 2 gateway replicas: 100 requests, 0 errors, 147.17 tok/s (host path: 327.51 tok/s). That is functional validation, not performance parity or production GPU serving.

The offline bundle (7.49 GiB, including model weights) was built and smoke-tested locally. It is **not published**, so it is not part of the public reproduction claim.

---

## Roles this fits

Inference engineering · Model deployment and quantization · AI platform engineering (serving and delivery) · MLOps

---

## Where I won't overclaim

- Every number applies only to this hardware, vLLM 0.29.0, and the stated context conditions — not to other GPUs or long-context workloads.
- The BF16 checkpoint does not fit in 8 GB, so it ran layer-wise on CPU as a quality baseline. **Its latency is not comparable to a GPU-resident vLLM model.**
- A 200-question multiple-choice set only supports "no accuracy difference observed on these 200 questions." Free-form text, code, long context, and domain data need separate evaluation.
- The cost calculator is a capacity-cost estimate. It excludes network, storage, labour, tax, and redundancy, and is not a cloud API quote.
- The 10-minute soak, HPA, and backpressure tests use a mock upstream; they validate gateway mechanics, not model throughput.
