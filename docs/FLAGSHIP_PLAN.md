# AI Inference Delivery Flagship Plan

This repository is the portfolio flagship for an **AI Systems / Inference
Engineer** profile. The target is a small, reproducible delivery platform that
turns a quantized model into an observable, testable, and deployable service.

## Definition of done

- A new user can run a CPU or mock smoke path without model weights or an API key.
- A GPU user can run the same gateway contract with the documented model/runtime bundle.
- The repository reports latency, throughput, quality, memory, and failure behaviour under
  fixed benchmark conditions.
- The service has health/readiness probes, bounded admission, structured logs, and metrics.
- Docker Compose is the primary local delivery path; Kubernetes is a validated deployment
  path with explicit GPU and storage assumptions.
- CI checks the deterministic path and rejects malformed configuration or broken contracts.
- The README and one-page report explain the engineering trade-offs without overstating
  results.

## Work sequence

### 0. Baseline and scope

- [x] Clone the repository and inspect the existing architecture.
- [x] Record the current commit, test commands, runtime assumptions, and known artifacts.
- [x] Remove or quarantine generated caches and machine-local files from the working tree.
- [x] Add a short contributor/developer runbook.

### 1. Reproducible local path

- [x] Make the gateway deterministic smoke path runnable without a GPU.
- [x] Pin the Python dependency and test entry points used by CI.
- [x] Add one command that runs unit tests, smoke checks, and configuration validation.
- [x] Document expected output and common failure modes.
- [x] Add a CI job that invokes the same local verification command.

### 2. Service contract and reliability

- [x] Review the OpenAI-compatible request/streaming contract.
- [x] Verify timeout, bounded concurrency, backpressure, cancellation, and error mapping.
- [x] Verify `/health`, `/live`, `/metrics`, and startup/shutdown behaviour.
- [x] Add focused tests for the failure paths that matter in production.
- [x] Add connect-only retry (never replay a read timeout).
- [x] Fix the keep-alive health-check flap found on Kubernetes.

### 3. Observability and benchmark harness

- [x] Define the service SLO vocabulary: TTFT, TPOT, end-to-end latency, queue time,
  throughput, error rate, GPU memory, and saturation.
- [x] Make benchmark metadata self-describing: model, runtime, GPU, driver, CUDA,
  prompt/output lengths, concurrency, repetitions, and git revision.
- [x] Produce a small report from machine-readable benchmark results.
- [x] Keep quality and performance results separate and show the per-question deltas.
- [x] Deploy Prometheus and scrape both gateway replicas by pod.

### 4. Container and Linux delivery

- [x] Validate the gateway image and Compose topology on Linux/WSL2.
- [x] Add a clean startup path with explicit model/runtime checks.
- [ ] Add a release checklist for images, model artifacts, checksums, and configuration.
- [x] Document the offline delivery boundary and what remains hardware-specific.

### 5. Kubernetes deployment

- [x] Validate the manifests with schema/lint checks.
- [x] Validate the gateway deployment with 2 replicas, probes, PDB, and rolling updates.
- [x] Document rollback and verify it with a deliberately broken image.
- [x] Add a deployment smoke test for the gateway layer.
- [x] Demonstrate GPU scheduling on WSL2 k3s with the NVIDIA device plugin and a GPU smoke pod.
- [x] Create a model PVC and load vLLM inside the cluster (model loaded; stable serving not achieved).
- [ ] Validate stable GPU scheduling and serving on a native Linux GPU node.
- [ ] Validate HPA with a working metrics-server.
- [ ] Move vLLM into a stable in-cluster serving path with a model PVC and GPU runtime class.

Verification evidence: [`K8S_VERIFICATION.md`](K8S_VERIFICATION.md),
[`K3S_GPU_EXPERIMENT.md`](K3S_GPU_EXPERIMENT.md), and the native Linux path in
[`LINUX_GPU_RUNBOOK.md`](LINUX_GPU_RUNBOOK.md).

### 6. Portfolio packaging

- [x] Rewrite the README around the problem, evidence, architecture, and trade-offs.
- [x] Add a positioning document for GitHub/profile use.
- [x] Add a concise performance report.
- [x] Add a concise resume-ready project summary.
- [ ] Publish a one-page English and Chinese case study with the new deployment results.
- [ ] Add a release-quality architecture diagram and benchmark table.

## Verification summary (2026-10-21)

| Check | Result |
|---|---|
| Gateway offline tests | 12 passed |
| Cost-calculator tests | 5 passed |
| Manifest validation | 16 documents passed |
| Kubernetes Service load | 100 requests, 0 errors, 326.53 tok/s |
| Pod kill during load | 300 requests, 0 errors, 315.46 tok/s |
| Pod replacement | Ready after 7.6 s |
| Bad-image rollback | Old replicas stayed Ready; `rollout undo` recovered |
| Prometheus | Both gateway pods `up`, both `upstream_healthy=1` |
| GPU scheduling (WSL2 k3s) | Demonstrated: node advertised `nvidia.com/gpu: 1`; GPU pod ran `nvidia-smi -L` |
| Stable in-cluster vLLM | Not achieved: `PLEG is not healthy`; see [`K3S_GPU_EXPERIMENT.md`](K3S_GPU_EXPERIMENT.md) |
| TensorRT-LLM | Not measured; protocol documented in [`RUNTIME_COMPARISON.md`](RUNTIME_COMPARISON.md) |

## Working rules

- Work on one stage at a time and leave a verification command or artifact for each stage.
- Do not claim a GPU or Kubernetes result unless it was run under the stated conditions.
- Prefer small changes with focused tests over broad rewrites.
- Keep secrets, model weights, caches, and machine-specific outputs out of Git.
