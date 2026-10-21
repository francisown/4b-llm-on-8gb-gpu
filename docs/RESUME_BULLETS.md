# Resume bullets

Use these only with the linked evidence. The numbers are from the validated
Docker vLLM + Kubernetes gateway path, not from the unstable WSL2 in-cluster
GPU experiment.

## One-line summary

> AI Systems / Inference Engineer who makes models fit constrained hardware and
> ships them as observable, testable services.

## Bullets

- **Quantized Qwen3.5-4B to 3.568 GiB INT4-AWQ on a single 8 GB RTX 5060**,
  evaluated on a frozen 200-question C-Eval set, and showed that equal aggregate
  accuracy (141/200) still hid 26 per-question disagreements versus BF16.
  Evidence: `benchmark/eval/quantization-final-comparison.csv`.

- **Built a FastAPI inference gateway with bounded admission, HTTP 429
  backpressure, SSE streaming, TTFT/latency histograms, JSON logs, connect-only
  retry, and graceful shutdown**; 12 offline tests run without a GPU or model.
  Evidence: `gateway/`, `gateway/test_gateway.py`.

- **Deployed the gateway on Kubernetes with 2 replicas, readiness/liveness
  probes, PDB, zero-downtime rollout, and per-pod Prometheus scraping**;
  measured **100 in-cluster requests at 0 errors and 326.53 tok/s**, p50
  500.3 ms, p95 513.8 ms.
  Evidence: `benchmark/results/k8s/service-load-c4.json`,
  `docs/K8S_VERIFICATION.md`.

- **Validated failure behaviour**: killing one gateway pod during 300 requests
  produced **0 errors** and 315.46 tok/s; replacement was Ready in 7.6 s; a
  deliberately broken image left both old replicas serving and `rollout undo`
  recovered.
  Evidence: `benchmark/results/k8s/pod-kill-under-load.json`,
  `benchmark/results/k8s/rollback.txt`.

- **Diagnosed and fixed a production-style health-check bug**: keep-alive reuse
  of a vLLM connection caused intermittent `RemoteProtocolError`, made one
  pod's health gauge drop to 0, and caused probe flapping; the fix disables
  keep-alive for `/health` and adds a regression test.

- **Documented the GPU/Kubernetes boundary honestly**: WSL2 k3s successfully
  scheduled a GPU pod and loaded vLLM into 6.9 GB VRAM, but the node failed
  with `PLEG is not healthy`, so stable in-cluster serving was not claimed.
  Evidence: `docs/K3S_GPU_EXPERIMENT.md`.

## What not to say

- Do not say "TensorRT-LLM measured" — it was not.
- Do not say "GPU inference runs in Kubernetes" — only the gateway does.
- Do not put the 54 tok/s custom-CUDA number and the 326.53 tok/s batched vLLM
  number in the same comparison column.
- Do not call the 326.53 tok/s a speedup over the 324.21 tok/s direct run; they
  are the same order of magnitude.
