# Evidence index

This directory holds 240+ raw result files. This page exists so you do not
have to guess which one still counts.

**Rule:** a file is *current* only if `README.md` or a file under `docs/`
links to it. Everything else is history — kept because it documents how a
number was reached, not because it is a claim you should quote.

## Claim → evidence

| Claim in the README | Current evidence | Notes |
|---|---|---|
| 2-hour real-vLLM soak: 67,530 req, 0 errors, p95 458.12 ms | [`real-vllm-docker-soak-c4-7200s.json`](real-vllm-docker-soak-c4-7200s.json) | Headline real-model number |
| 30-minute real-vLLM soak: 17,609 req, p95 433.79 ms | [`real-vllm-docker-soak-c4-1800s.json`](real-vllm-docker-soak-c4-1800s.json) | Shorter comparison point |
| 10-minute real-vLLM soak | [`real-vllm-docker-soak-c4-600s.json`](real-vllm-docker-soak-c4-600s.json) | Early sanity run |
| 3 × 20 requests, 325.71 tok/s mean | [`real-vllm-v0.2.4-3runs-summary.json`](real-vllm-v0.2.4-3runs-summary.json) | Aggregates the three `-run1/2/3` files |
| 2-hour mock-gateway soak: 140,178 req | [`observability/soak-c4-7200s-v0.2.4.json`](observability/soak-c4-7200s-v0.2.4.json) | Mock upstream, gateway mechanics only |
| c=16 backpressure: 621 ok + 6,544 clean 429s | [`observability/backpressure-c16-30s.json`](observability/backpressure-c16-30s.json) | |
| Quantization quality table | [`../eval/quantization-final-comparison.csv`](../eval/quantization-final-comparison.csv) | Regenerated from raw JSON; CI checks it |
| Queue-depth HPA 2→4→6→5→4→3→2 | [`k8s-hpa-queue/scale-test.txt`](k8s-hpa-queue/scale-test.txt) | Plus `setup.txt` for the metric wiring |
| TLS + enforced NetworkPolicy | [`k8s-tls/networkpolicy-matrix.txt`](k8s-tls/networkpolicy-matrix.txt) | Plus `tls-endpoints.txt` |
| Alertmanager webhook delivery | [`observability/alertmanager-webhook.txt`](observability/alertmanager-webhook.txt) | firing + resolved POSTs |
| CPU HPA 2→4→2 | [`hpa/summary-v0.2.4.json`](hpa/summary-v0.2.4.json) | Superseded in spirit by queue-depth HPA, still valid for CPU |

## Directories

| Path | Contents | Status |
|---|---|---|
| `speculative/` (58 files) | Speculative-decoding sweep: baseline vs draft-model runs at c1/c4, GPU memory traces, per-run logs | Historical; the conclusion lives in `docs/PERFORMANCE_REPORT.md`, not in any single file |
| `rebaseline/` (12 files) | Server logs and GPU state captured while re-establishing a clean baseline | Historical reference for "what the machine looked like" |
| `observability/` (27 files) | Soaks, backpressure, TLS/alert/webhook smoke, Grafana/Jaeger responses | Mixed: several are current, several are pre-v0.2.4 snapshots |
| `k8s/` (18 files) | In-cluster load, pod-kill, rollout evidence | Current for `docs/K8S_VERIFICATION.md` |
| `k8s-gpu/` (10 files) | WSL2 k3s GPU-in-K8s smoke and the NotReady failure | Current, but explicitly *not* a stability claim |
| `k8s-tls/` (6 files) | TLS endpoints, NetworkPolicy toggle matrix, applied manifests | Current |
| `k8s-hpa-queue/` (2 files) | Queue-depth HPA setup and the c=32 scale trace | Current |
| `hpa/` (5 files) | CPU HPA run on `hpa-demo` | Current for the CPU variant |
| `runner-verify/` (3 files) | v1/v2 model-runner verification logs | Historical |
| root (120 files) | Concurrency sweeps, quantization variants, quality JSON, repeat runs | Mostly historical; `qwen35-int4-awq-self-compiled-c4.json` is the current throughput input for `tools/cost_calculator.py` |

## How to tell a file is stale

Any of these means do not quote it as a current number:

- It has a `v0.1`/`v0.2.0`–`v0.2.3` suffix and a newer `v0.2.4` counterpart exists.
- It is a single-run file when a `-3runs-summary.json` covers the same config.
- It uses the mock upstream but sits outside `observability/` or `hpa/`.
- It predates 2026-10-21 (the v0.2.4 measurement day) and is quoted nowhere in `docs/`.

If a claim and its evidence disagree, the `docs/` file wins and this index is
wrong — fix the index.
