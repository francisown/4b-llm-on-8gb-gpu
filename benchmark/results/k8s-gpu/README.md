# GPU-in-Kubernetes (WSL2 k3s) validation

Date: **2026-10-21**. This is a single-node WSL2 k3s experiment, not a
production GPU platform.

## What ran

- k3s **v1.37.1+k3s1** on WSL2 Ubuntu 22.04, RTX 5060 8 GB, driver 595.97.
- NVIDIA device plugin in `kube-system`; node advertises `nvidia.com/gpu: 1`.
- `vllm` Deployment: `ai-inference-vllm:0.29.0-cu130`, runtime class `nvidia`,
  one GPU, model mounted from hostPath.
- `inference-gateway` Deployment: 2 replicas of `ai-inference-gateway:v0.2.4`,
  pointing at `http://vllm:8000`.
- In-cluster load generator: 100 requests, concurrency 4, 64 output tokens.

The manifests are in [`k8s/gpu-inference/`](../../../k8s/gpu-inference/).

## Results

| Metric | Result |
|---|---:|
| Gateway replicas Ready | **2 / 2** |
| vLLM pod | **1 / 1**, `nvidia.com/gpu: 1` |
| In-cluster requests / errors | **100 / 0** |
| Output throughput | **147.17 tok/s** |
| Latency mean / p50 / p95 / p99 | 1112.54 / 561.64 / 3019.92 / 3040.28 ms |
| Pod distribution | 50 / 50 |
| Stream requests / errors | **20 / 0** |
| Stream TTFT p50 / p95 | **91.8 / 113.2 ms** |
| Stream throughput | 81.57 tok/s |

Evidence: [`loadgen-v0.2.4.json`](loadgen-v0.2.4.json),
[`stream-v0.2.4.json`](stream-v0.2.4.json),
[`pods.txt`](pods.txt), [`gpu-allocatable.txt`](gpu-allocatable.txt),
[`node.txt`](node.txt), and [`vllm-log.txt`](vllm-log.txt).

## What was fixed

Kubernetes injects `VLLM_PORT=tcp://<service-ip>:8000` for a Service named
`vllm`. vLLM 0.29 interprets `VLLM_PORT` as an integer and crashed during engine
startup. The pod sets `VLLM_PORT=8000` explicitly and disables service links.
After that, the engine started and served requests.

An older `ai-inference` namespace with crash-looping gateway/vLLM pods was
deleted before this run; it was a separate failed experiment, not part of this
manifest set.

## Limits

- The in-cluster throughput is much lower than the host path: the host gateway
  measured 327.51 tok/s and p95 513 ms on the same model; this k3s run measured
  147.17 tok/s and p95 3020 ms. The cause is not yet isolated (CPU cgroup,
  WSL2/k3s GPU scheduling, or another factor). Do not call this parity.
- One node, one GPU, one model replica; no high availability for the model.
- The model is mounted with `hostPath`; the namespace therefore does not enforce
  Pod Security `baseline` (audit/warn only). A production deployment should use
  a PVC and a GPU node pool.
- 100 requests is a short smoke test, not a soak. No multi-hour GPU serving or
  memory-leak result is claimed.
- This is WSL2 k3s; it is not a claim about native Linux GPU clusters.
