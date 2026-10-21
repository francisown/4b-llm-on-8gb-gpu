# Changelog

## 0.2.1 — 2026-10-21

- Add optional `Authorization: Bearer` / `X-API-Key` authentication for chat
  endpoints; health, liveness, and metrics remain open for probes/Prometheus.
- Add the `inference_gateway_auth_failures_total` metric and two auth tests
  (14 gateway tests total).
- Add a CPU-only Compose observability stack with mock vLLM, Prometheus, and a
  provisioned Grafana dashboard.
- Add SLO/error-budget documentation, a release checklist, and a
  tag-triggered GHCR release workflow.
- Add a repeatable gateway soak and a concurrency-16 backpressure test.
- Remove out-of-scope financial research and career files from this repository;
  move the inference-ops agent to `experiments/inference-ops-agent/`.
- Version the gateway image as `v0.2.1`; do not reuse the `v0.2.0` tag for the
  auth change.

## 0.2.0 — 2026-10-20

- Validate the Kubernetes gateway layer with two replicas, readiness/liveness,
  PDB, zero-downtime rollout/rollback, and per-pod Prometheus.
- Add the in-cluster load test and pod-kill-under-load evidence.
- Add CI (tests, manifest validation, Kustomize render, Docker build).
- Add the WSL2 k3s GPU experiment and the native Linux GPU runbook.

## 0.1.0 — 2026-09

- Initial 8 GB Qwen3.5-4B quantization, quality evaluation, vLLM serving, and
  Docker delivery work.
