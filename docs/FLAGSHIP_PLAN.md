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

### 5. Reproducible local path

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
- [x] Add optional per-identity rate limiting (API key or client IP).
- [x] Fix the keep-alive health-check flap found on Kubernetes.

### 3. Observability and benchmark harness

- [x] Define the service SLO vocabulary: TTFT, TPOT, end-to-end latency, queue time,
  throughput, error rate, GPU memory, and saturation.
- [x] Make benchmark metadata self-describing: model, runtime, GPU, driver, CUDA,
  prompt/output lengths, concurrency, repetitions, and git revision.
- [x] Produce a small report from machine-readable benchmark results.
- [x] Keep quality and performance results separate and show the per-question deltas.
- [x] Deploy Prometheus and scrape both gateway replicas by pod.
- [x] Deploy a Grafana dashboard and document SLOs/error budget.
- [x] Add TLS termination and Prometheus alert rules.
- [x] Add OpenTelemetry tracing with Jaeger and a Grafana datasource.
- [x] Add a repeatable gateway soak and run 2-minute and 10-minute tests (2,329 and 11,717 requests, 0 errors).

### 4. Container and Linux delivery

- [x] Validate the gateway image and Compose topology on Linux/WSL2.
- [x] Add a clean startup path with explicit model/runtime checks.
- [x] Add a release checklist for images, model artifacts, checksums, and configuration.
- [x] Add a tag-triggered release workflow, Dependabot, and security/contribution docs.
- [x] Publish v0.2.5 to GHCR and create a GitHub Release.
- [x] Add a single benchmark protocol and repository navigation docs.
- [x] Remove out-of-scope financial research and career files.
- [x] Document the offline delivery boundary and what remains hardware-specific.

### 5. Kubernetes deployment

- [x] Validate the manifests with schema/lint checks.
- [x] Validate the gateway deployment with 2 replicas, probes, PDB, and rolling updates.
- [x] Document rollback and verify it with a deliberately broken image.
- [x] Add a deployment smoke test for the gateway layer.
- [x] Demonstrate GPU scheduling on WSL2 k3s with the NVIDIA device plugin and a GPU smoke pod.
- [x] Create a model PVC and load vLLM inside the cluster (model loaded; stable serving not achieved).
- [ ] Validate stable GPU scheduling and serving on a native Linux GPU node.
- [x] Validate HPA with a working metrics-server.
- [ ] Move vLLM into a stable in-cluster serving path with a model PVC and GPU runtime class.

Verification evidence: [`K8S_VERIFICATION.md`](K8S_VERIFICATION.md),
[`K3S_GPU_EXPERIMENT.md`](K3S_GPU_EXPERIMENT.md), and the native Linux path in
[`LINUX_GPU_RUNBOOK.md`](LINUX_GPU_RUNBOOK.md).

### 6. Portfolio packaging

- [x] Rewrite the README around the problem, evidence, architecture, and trade-offs.
- [x] Add a positioning document for GitHub/profile use.
- [x] Add a concise performance report.
- [x] Add a concise resume-ready project summary.
- [x] Publish a one-page English and Chinese case study with the new deployment results.
- [x] Add a release-quality architecture diagram and benchmark table.

## Verification summary (2026-10-21)

| Check | Result |
|---|---|
| Gateway offline tests | 19 passed |
| Workflow validation | 2 workflow files passed |
| Release v0.2.4 | GHCR image `sha256:4453ef462ac426b6abe239819d41a4171454f7ebffacaf90ffb481a8f95e1365`; GitHub Release created; release workflow run 4 succeeded; CI runs 38/39 succeeded |
| Optional API-key auth | 401 without key; 200 with `X-API-Key` or `Authorization: Bearer`; health/metrics stay open |
| Per-identity rate limit | v0.2.4: auth disabled, tenant A 5×200 then 429 and key rotation stays limited; auth enabled, tenant A 5×200 then 429 while tenant B remains 200 |
| Cost-calculator tests | 5 passed |
| Manifest validation | 17 documents passed |
| Kubernetes Service load | 100 requests, 0 errors, 326.53 tok/s |
| Pod kill during load | 300 requests, 0 errors, 315.46 tok/s |
| Pod replacement | Ready after 7.6 s |
| Bad-image rollback | Old replicas stayed Ready; `rollout undo` recovered |
| Prometheus | Both gateway pods `up`, both `upstream_healthy=1` |
| HPA | 2→4 in 45s, 4→2 in 90s; 8,000 requests at c=32, 0 errors, CPU 198%/60% (mock upstream) |
| Grafana demo | Datasource `Prometheus`; dashboard `Inference Gateway`; 20 non-stream + 5 stream smoke requests; health ok |
| TLS | HTTPS `/health` and `/chat` returned 200 through Nginx with a self-signed cert |
| Alert rules | 5 rules loaded in Prometheus (upstream, errors, TTFT, queue wait, no-success) |
| OTel/Jaeger | `inference-gateway` service; 5 traces; first trace 4 spans; no export errors |
| Gateway soak (mock upstream) | v0.2.4 120 s: 2,329 requests, 0 errors, 19.389 req/s, p95 215.82 ms; v0.2.4 600 s: 11,717 requests, 0 errors, 19.525 req/s, p95 213.62 ms; gauges 0 after drain |
| Backpressure (c=16) | 621 success / 6,544 clean 429 / 0 other errors; gauges 0 after drain |
| GPU scheduling (WSL2 k3s) | Demonstrated: node advertised `nvidia.com/gpu: 1`; GPU pod ran `nvidia-smi -L` |
| Stable in-cluster vLLM | Not achieved: `PLEG is not healthy`; see [`K3S_GPU_EXPERIMENT.md`](K3S_GPU_EXPERIMENT.md) |
| TensorRT-LLM | Not measured; protocol documented in [`RUNTIME_COMPARISON.md`](RUNTIME_COMPARISON.md) |

## Working rules

- Work on one stage at a time and leave a verification command or artifact for each stage.
- Do not claim a GPU or Kubernetes result unless it was run under the stated conditions.
- Prefer small changes with focused tests over broad rewrites.
- Keep secrets, model weights, caches, and machine-specific outputs out of Git.
