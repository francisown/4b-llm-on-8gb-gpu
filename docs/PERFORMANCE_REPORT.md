# Performance report: 8 GB inference delivery

This is a concise, portfolio-facing report. Every number below is tied to a
raw result file and a fixed environment. See
[`BENCHMARK_PROTOCOL.md`](BENCHMARK_PROTOCOL.md) for the protocol matrix;
single-run rows are indicative. Do not extrapolate to other GPUs, models,
context lengths, or concurrency levels.

## Environment

| Item | Value |
|---|---|
| GPU | NVIDIA RTX 5060, 8,151 MiB |
| Model | Qwen3.5-4B-INT4-AWQ-self |
| Runtime | vLLM 0.29.0 |
| Host | Windows + WSL2 Ubuntu 22.04; Docker Desktop Kubernetes for the gateway |
| Gateway | FastAPI `ai-inference-gateway:v0.2.0` for the measured run; `v0.2.1` adds optional API-key auth without changing the serving path |
| Model server | vLLM in a Docker container with GPU access; **not** scheduled by Kubernetes |
| Prometheus | v2.55.1, scraping both gateway pods |

## 1. Quantization quality

Frozen C-Eval `val` set, 200 questions, 52 subjects, temperature 0, thinking
disabled, max 8 output tokens. The point is not a single accuracy number; it is
per-question behaviour.

| Model | Size | Accuracy | Agreement with BF16 | Fixed BF16 errors | Broke BF16 correct |
|---|---:|---:|---:|---:|---:|
| BF16 reference | 8.701 GiB | 141/200 (70.5%) | 100.0% | — | — |
| Third-party FP8 | 5.281 GiB | 141/200 (70.5%) | 96.5% | 3 | 3 |
| Self-made FP8 v3 | 5.281 GiB | 141/200 (70.5%) | 98.0% | 2 | 2 |
| Self-made INT4-AWQ v1 | **3.568 GiB** | 141/200 (70.5%) | **87.0%** | 11 | 11 |

All four score 141/200, but INT4 disagrees with BF16 on 26 questions. Equal
totals do not mean equal models.

Raw data: [`benchmark/eval/`](../benchmark/eval/).

## 2. Kubernetes gateway performance

Validated on Docker Desktop Kubernetes v1.36.1, two gateway replicas, real vLLM
upstream, `temperature=0`, thinking disabled.

### In-cluster Service load

| Metric | Result |
|---|---:|
| Requests / concurrency | 100 / 4 |
| Duration | 12.556 s |
| Throughput | **7.964 req/s** |
| Output throughput | **326.53 tok/s** |
| Latency p50 / p95 / p99 | 500.30 / 513.81 / 523.28 ms |
| Errors | **0 / 100** |
| Pod distribution | 25 / 75 |

Raw: [`service-load-c4.json`](../benchmark/results/k8s/service-load-c4.json).

### Streaming TTFT

| Metric | Result |
|---|---:|
| Requests / concurrency | 20 / 4 |
| Output throughput | 312.94 tok/s |
| TTFT p50 / p95 / p99 | **96.1 / 138.6 / 141.8 ms** |
| End-to-end p50 / p95 | 514.0 / 565.62 ms |
| Errors | 0 / 20 |

Raw: [`stream-c4.json`](../benchmark/results/k8s/stream-c4.json).

The 326.53 tok/s Service run and the 324.21 tok/s direct run are the same order
of magnitude; this is evidence that the gateway/K8s layer did not introduce a
large throughput penalty, not a claim of a speedup.

### Pod kill during live load

| Metric | Result |
|---|---:|
| Requests / concurrency | 300 / 4 |
| Duration | 30.432 s |
| Throughput | 9.858 req/s |
| Output throughput | 315.457 tok/s |
| Latency p50 / p95 / p99 | 403.16 / 425.71 / 428.30 ms |
| Errors | **0 / 300** |
| Pod distribution | victim 54 / survivor 246 |

Raw: [`pod-kill-under-load.json`](../benchmark/results/k8s/pod-kill-under-load.json).

## 3. Failure handling

| Test | Result |
|---|---|
| Delete one gateway pod | Replacement Ready after **7.6 s**; Service endpoints updated |
| Bad image rollout | New pod `ImagePullBackOff`; both old replicas stayed Ready |
| `kubectl rollout undo` | Returned to `v0.2.0`; rollout succeeded |
| Prometheus targets | Both gateway pods `up`; `upstream_healthy=1` |

Raw: [`pod-kill.txt`](../benchmark/results/k8s/pod-kill.txt),
[`rollback.txt`](../benchmark/results/k8s/rollback.txt),
[`prometheus-targets.json`](../benchmark/results/k8s/prometheus-targets.json).

## 4. Gateway soak (mock upstream)

This is a gateway-stability test, not a model-throughput benchmark. It ran
against the CPU-only mock OpenAI-compatible upstream, so it isolates the
gateway's admission control, connection handling, and gauge cleanup.

| Metric | Result |
|---|---:|
| Duration / concurrency | 120.106 s / 4 |
| Requests | **2,329** |
| Errors | **0** |
| Throughput | 19.391 req/s |
| Latency mean / p50 / p95 / p99 | 206.25 / 205.49 / 216.64 / 223.78 ms |
| Health before / after | ok / ok |
| Active / waiting after drain | **0 / 0** |

Raw: [`soak-c4-120s.json`](../benchmark/results/observability/soak-c4-120s.json).

The value of this test is the **zero-error completion and gauge recovery**,
not the latency number: the mock upstream has a fixed delay, so the latency is
not comparable to vLLM.

### Backpressure at concurrency 16

| Metric | Result |
|---|---:|
| Attempts / concurrency | 7,165 / 16 |
| Success (200) | 621 |
| Rejected (429) | 6,544 |
| Other errors | **0** |
| Rejection rate | 91.3% |
| Successful-request p95 | 473.89 ms |
| Active / waiting after drain | **0 / 0** |

At concurrency 16 against a gateway configured for 4 active + 4 queued
requests, most requests are shed with **429** instead of timing out or
returning 5xx. This is the intended backpressure behavior; the 429s are
counted separately from unexpected errors. Raw:
[`backpressure-c16-30s.json`](../benchmark/results/observability/backpressure-c16-30s.json).

## 5. What is not in this report

- **No TensorRT-LLM result.** The comparison protocol and harness exist; no
  engine was built or measured. See [`RUNTIME_COMPARISON.md`](RUNTIME_COMPARISON.md).
- **No stable in-cluster GPU vLLM result.** The WSL2 k3s attempt scheduled a GPU
  pod and loaded the model, but the node failed with `PLEG is not healthy`.
  No in-cluster serving numbers are claimed. See
  [`K3S_GPU_EXPERIMENT.md`](K3S_GPU_EXPERIMENT.md).
- **No multi-node or multi-GPU result.**
- **No long-duration soak or memory-leak result.**
- **No cloud cost quote.** The cost calculator is a capacity estimate, not an
  accounting system.

## 6. Reproduce

```bash
python scripts/verify_local.py
python scripts/validate_manifests.py

# Start vLLM with GPU access, then run the gateway + K8s path:
kubectl apply -k k8s
kubectl apply -k k8s/observability
kubectl apply -f k8s/benchmark/loadgen-job.yaml
```

The full command sequence is in
[`K8S_VERIFICATION.md`](K8S_VERIFICATION.md); the native Linux GPU path is in
[`LINUX_GPU_RUNBOOK.md`](LINUX_GPU_RUNBOOK.md).
