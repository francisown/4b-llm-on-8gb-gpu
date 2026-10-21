# Portfolio positioning: AI Systems / Inference Engineer

## One-line positioning

> **AI Systems / Inference Engineer** — I make a model fit the hardware, then
> turn it into an observable, verifiable, and deliverable service.

This is deliberately narrower than "AI engineer". The work is not training a
new foundation model. It is the engineering between a checkpoint and a running
service: quantization under a VRAM budget, serving, latency/throughput
measurement, Kubernetes, observability, failure handling, and delivery.

## Evidence map

| Repository / artifact | What it proves |
|---|---|
| [`8gb-llm-inference-delivery`](https://github.com/francisown/8gb-llm-inference-delivery) | Quantization on an 8 GB card, quality deltas, vLLM serving, FastAPI gateway, Docker, Kubernetes, Prometheus, rollout/rollback, measured TTFT/throughput |
| [`qwen3.5-fp8-cuda`](https://github.com/francisown/qwen3.5-fp8-cuda) | Hand-written CUDA kernels, FP8 inference, memory/throughput tuning at the engine level |
| [`filingcopilot`](https://github.com/francisown/filingcopilot) | FastAPI, RAG/SQLite, LangGraph, MCP, financial data, traceable evidence |
| `rgb-to-depth` (local) | TensorRT, CUDA Graph, CMake, prebuilt wheels, video batching, real deployment delivery |
| `Qwen3.5-4B-INT4-Docker-Offline-20260918` (local) | Model + image + scripts + checksums as an offline bundle |
| `FilingTime-Auditor`, `card-abs-radar`, `自进化agent` (local) | Evidence chains, deterministic validation, fail-closed design, agent evaluation, governance |

The first two rows are the core inference story. The financial-agent projects
are evidence of reliable, auditable system design; they should not be expanded
indefinitely.

## What is actually verified in this repository

| Claim | Evidence |
|---|---|
| INT4-AWQ fits a 4B model into 3.568 GiB | `benchmark/eval/quantization-final-comparison.csv` |
| Four quantizations score 141/200 but disagree per-question | `benchmark/eval/` per-question JSON |
| vLLM serves the model on RTX 5060 | real `/v1/models` and `/chat` runs documented in `docs/K8S_VERIFICATION.md` |
| Gateway streams with TTFT p50 96.1 ms | `benchmark/results/k8s/stream-c4.json` |
| Kubernetes Service handles 100 requests at 0 errors | `benchmark/results/k8s/service-load-c4.json` |
| Killing a pod during 300 requests causes 0 errors | `benchmark/results/k8s/pod-kill-under-load.json` |
| Bad rollout keeps old replicas serving | `benchmark/results/k8s/rollback.txt` |
| Prometheus scrapes both replicas | `benchmark/results/k8s/prometheus-targets.json` |
| GPU scheduling in K8s was demonstrated on WSL2 k3s; stable serving was blocked by PLEG | [`K3S_GPU_EXPERIMENT.md`](K3S_GPU_EXPERIMENT.md) |

## What is not claimed

- No training or pretraining result.
- No TensorRT-LLM performance number. The comparison protocol is documented in
  [`RUNTIME_COMPARISON.md`](RUNTIME_COMPARISON.md), but no result is invented.
- No stable GPU-in-Kubernetes serving result. Docker Desktop K8s has no NVIDIA
  device plugin; WSL2 k3s scheduled a GPU pod and loaded vLLM, but
  `PLEG is not healthy` blocked stable serving. See
  [`K3S_GPU_EXPERIMENT.md`](K3S_GPU_EXPERIMENT.md).
- No production SLA, multi-tenant isolation, TLS, or authentication.
- No claim that the 54 tok/s custom-CUDA engine is directly comparable to the
  batched vLLM service.

## GitHub profile blurb (ready to paste)

```text
AI Systems / Inference Engineer
I make models fit the hardware, then ship them as observable, verifiable services.

Currently: Qwen3.5-4B INT4-AWQ on a single RTX 5060 (8 GB) — quantization,
quality deltas, vLLM serving, TTFT/TPOT/throughput benchmarks, FastAPI gateway,
Docker/Kubernetes, Prometheus, zero-downtime rollout and rollback.

Also: hand-written CUDA/FP8 inference kernels, TensorRT video deployment,
and reliable financial-agent systems with evidence trails.
```

## Next 6–12 weeks

1. **Linux GPU node + NVIDIA device plugin.** Move vLLM into Kubernetes and
   prove `nvidia.com/gpu` scheduling, model PVC, cold start, and a GPU-aware
   readiness probe.
2. **TensorRT-LLM on the same checkpoint.** Build an INT4-AWQ/FP8 engine and run
   the same protocol; publish a real comparison with TTFT, TPOT, throughput,
   VRAM, and quality.
3. **SLO and dashboards.** Add Grafana dashboards for TTFT/TPOT, queue depth,
   error rate, GPU utilization, and VRAM; define alert thresholds.
4. **Soak and failure testing.** Long-running load, memory-leak checks, vLLM
   restart, node drain, and canary rollout.
5. **Package the story.** One-page case study (EN/ZH), updated resume bullets,
   and a short architecture diagram that separates the gateway layer from the
   GPU inference layer.
