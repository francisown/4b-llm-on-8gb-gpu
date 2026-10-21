# Changelog

## 0.2.4 — 2026-10-21

- Harden per-identity rate limiting: a key is used as identity only when
  authentication is configured; otherwise the direct client IP is used.
- Bound the in-memory rate-limit identity map (`GATEWAY_RATE_LIMIT_MAX_IDENTITIES`)
  and add `GATEWAY_API_KEYS` for multiple authenticated keys.
- Return `502` with a structured error when the upstream returns malformed JSON,
  instead of leaking an unhandled `500`.
- Expand the gateway suite to 19 tests, including window expiry, identity-map
  bounds, auth + rate-limit interaction, and malformed upstream responses.
- Regenerate `benchmark/eval/quantization-final-comparison.csv` from the raw
  three-run evidence and add `--check` enforcement.
- Reconcile the HPA narrative with the actual `hpa-demo` validation, fix stale
  links/numbers, and add Markdown link + manifest-count checks to CI.
- Use `docs/RELEASE.md` as the GitHub Release body for future tags.
- Re-run the HPA test on v0.2.4 (2→4 in 45 s, 4→2 in 90 s, 8,000
  requests/0 errors) and run a 10-minute v0.2.4 mock soak (11,717 requests,
  0 errors, p95 213.62 ms).
- Run a 2-hour v0.2.4 mock soak: 140,178 requests, 0 errors, 19.469 req/s,
  p95 214.82 ms; active/waiting return to 0.

## 0.2.3 — 2026-10-21

- Add optional per-identity rate limiting (`GATEWAY_RATE_LIMIT_PER_MINUTE`),
  keyed by API key or client IP, with a regression test (15 gateway tests).
- Validate HPA 2→4→2 on Docker Desktop Kubernetes with metrics-server and a
  mock upstream: 8,000 requests at c=32, 0 errors; CPU 196%/60%; scale-up 45s,
  scale-down 80s.
- Run a 10-minute gateway soak: 11,554 requests, 0 errors, p95 217.39 ms;
  active/waiting return to 0.

## 0.2.2 — 2026-10-21

- Add a local Nginx TLS terminator with a self-signed certificate and HTTPS
  health/chat verification.
- Add five Prometheus alert rules (upstream health, error rate, TTFT p95,
  queue-wait p95, no-successful-requests) and a runbook.
- Add OpenTelemetry auto-instrumentation and Jaeger OTLP tracing, with a
  Grafana Jaeger datasource and trace verification.
- Enable OTel only in the Compose observability stack; the image defaults to
  `OTEL_SDK_DISABLED=true` for standalone/Kubernetes runs.

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
