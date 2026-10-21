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
| Gateway | FastAPI `ai-inference-gateway:v0.2.0` for the measured run; v0.2.1 adds auth, v0.2.2 adds TLS/alerting/OTel, v0.2.3 adds rate limiting, and v0.2.4 hardens auth/rate-limit identity handling without changing the serving path |
| Model server | vLLM host container for the original K8s numbers; a separate short WSL2 k3s GPU smoke also ran vLLM in-cluster |
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

## 2. Gateway v0.2.4 real-model tests (host)

This is a host-gateway run against the real vLLM server in Docker Desktop,
separate from the original v0.2.0 Kubernetes benchmark. Three independent
batches were run per mode.

| Metric | Non-stream (3-run mean) | Stream (3-run mean) |
|---|---:|---:|
| Requests / concurrency | 20 / 4 per run | 20 / 4 per run |
| Errors | 0 | 0 |
| Output throughput | **325.71 tok/s** (324.15–327.87) | **324.91 tok/s** |
| Latency p50 / p95 | 502.83 / 512.92 ms | 516.11 ms p95 |
| TTFT p50 / p95 | — | **82.4 / 98.47 ms** |

Raw: [`real-vllm-v0.2.4-3runs-summary.json`](../benchmark/results/real-vllm-v0.2.4-3runs-summary.json).

### 10-minute real-vLLM soak

| Metric | Result |
|---|---:|
| Duration / concurrency | 600.064 s / 4 |
| Requests | **5,992** |
| Errors | **0** |
| Throughput | 9.986 req/s |
| Latency mean / p50 / p95 / p99 | 400.57 / 395.83 / 418.49 / 538.67 ms |
| Health before / after | ok / ok |
| Active / waiting after drain | **0 / 0** |

Raw: [`real-vllm-docker-soak-c4-600s.json`](../benchmark/results/real-vllm-docker-soak-c4-600s.json).
This is a real-model gateway soak on one host, not a Kubernetes GPU soak.

### 30-minute real-vLLM soak

| Metric | Result |
|---|---:|
| Duration / concurrency | 1800.281 s / 4 |
| Requests | **17,609** |
| Errors | **0** |
| Throughput | 9.781 req/s |
| Latency mean / p50 / p95 / p99 | 408.94 / 410.99 / 433.79 / 455.82 ms |
| Health before / after | ok / ok |
| Active / waiting after drain | **0 / 0** |

Raw: [`real-vllm-docker-soak-c4-1800s.json`](../benchmark/results/real-vllm-docker-soak-c4-1800s.json).

## 3. Kubernetes gateway performance

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

### WSL2 k3s GPU-in-K8s smoke

A later short run put vLLM inside WSL2 k3s with `nvidia.com/gpu: 1`, behind two
gateway replicas:

| Metric | Result |
|---|---:|
| Requests / concurrency | 100 / 4 |
| Errors | **0 / 100** |
| Output throughput | **147.17 tok/s** |
| Latency mean / p50 / p95 / p99 | 1112.54 / 561.64 / 3019.92 / 3040.28 ms |
| Pod distribution | 50 / 50 |
| Stream requests / TTFT p50 / p95 | 20 / **91.8 / 113.2 ms** |

This is functional validation, not parity: the host path measured 327.51 tok/s
and p95 513 ms. The in-cluster gap is not yet isolated. After roughly six hours
the node became `NotReady` (flannel/PLEG), so no long-run GPU/K8s soak is
claimed. Raw: [`benchmark/results/k8s-gpu/`](../benchmark/results/k8s-gpu/).

## 4. Failure handling

| Test | Result |
|---|---|
| Delete one gateway pod | Replacement Ready after **7.6 s**; Service endpoints updated |
| Bad image rollout | New pod `ImagePullBackOff`; both old replicas stayed Ready |
| `kubectl rollout undo` | Returned to `v0.2.0`; rollout succeeded |
| Prometheus targets | Both gateway pods `up`; `upstream_healthy=1` |

Raw: [`pod-kill.txt`](../benchmark/results/k8s/pod-kill.txt),
[`rollback.txt`](../benchmark/results/k8s/rollback.txt),
[`prometheus-targets.json`](../benchmark/results/k8s/prometheus-targets.json).

## 5. Gateway soak (mock upstream)

This is a gateway-stability test, not a model-throughput benchmark. It ran
against the CPU-only mock OpenAI-compatible upstream, so it isolates the
gateway's admission control, connection handling, and gauge cleanup.

| Metric | Result |
|---|---:|
| Duration / concurrency | 120.119 s / 4 |
| Requests | **2,329** |
| Errors | **0** |
| Throughput | 19.389 req/s |
| Latency mean / p50 / p95 / p99 | 206.29 / 205.58 / 215.82 / 221.86 ms |
| Health before / after | ok / ok |
| Active / waiting after drain | **0 / 0** |

Raw: [`soak-c4-120s-v0.2.4.json`](../benchmark/results/observability/soak-c4-120s-v0.2.4.json).

The value of this test is the **zero-error completion and gauge recovery**,
not the latency number: the mock upstream has a fixed delay, so the latency is
not comparable to vLLM.

### 10-minute soak (v0.2.4)

| Metric | Result |
|---|---:|
| Duration / concurrency | 600.092 s / 4 |
| Requests | **11,717** |
| Errors | **0** |
| Throughput | 19.525 req/s |
| Latency mean / p50 / p95 / p99 | 204.86 / 204.16 / 213.62 / 219.19 ms |
| Health before / after | ok / ok |
| Active / waiting after drain | **0 / 0** |

Raw: [`soak-c4-600s-v0.2.4.json`](../benchmark/results/observability/soak-c4-600s-v0.2.4.json).
This is a 10-minute gateway soak, not a multi-hour model soak.

### 2-hour soak (v0.2.4)

| Metric | Result |
|---|---:|
| Duration / concurrency | 7200.186 s / 4 |
| Requests | **140,178** |
| Errors | **0** |
| Throughput | 19.469 req/s |
| Latency mean / p50 / p95 / p99 | 205.46 / 204.84 / 214.82 / 220.03 ms |
| Health before / after | ok / ok |
| Active / waiting after drain | **0 / 0** |

Raw: [`soak-c4-7200s-v0.2.4.json`](../benchmark/results/observability/soak-c4-7200s-v0.2.4.json).
This is a 2-hour gateway soak against the mock upstream, not a multi-hour
GPU/model soak.

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

## 6. What is not in this report

- **No TensorRT-LLM result.** The comparison protocol and harness exist; no
  engine was built or measured. See [`RUNTIME_COMPARISON.md`](RUNTIME_COMPARISON.md).
- **Short in-cluster GPU smoke, not a production result.** A WSL2 k3s run put
  vLLM and the gateway inside the cluster: 100 in-cluster requests, 0 errors,
  **147.17 tok/s**, p95 **3019.92 ms**; stream TTFT p50 **91.8 ms**. The host
  path measured 327.51 tok/s and p95 513 ms. The cause of the in-cluster gap is
  not isolated, and this is not a performance-parity claim. See
  [`benchmark/results/k8s-gpu/`](../benchmark/results/k8s-gpu/).
- **No multi-node or multi-GPU result.**
- **No multi-hour GPU/K8s soak or memory-leak profile.** The 2-hour soak is a
  gateway test against the mock upstream; it is not a model or GPU endurance
  result.
- **No cloud cost quote.** The cost calculator is a capacity estimate, not an
  accounting system.

## 7. Reproduce

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
