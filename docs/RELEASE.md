# Release v0.2.3

Release date: **2026-10-21**

- GitHub Release: <https://github.com/francisown/8gb-llm-inference-delivery/releases/tag/v0.2.3>
- Tag: `v0.2.3`
- Image: `ghcr.io/francisown/8gb-llm-inference-delivery/gateway:v0.2.3`
- Digest: published by the release workflow; see the release/package page.

## Pull

```bash
docker pull ghcr.io/francisown/8gb-llm-inference-delivery/gateway:v0.2.3
```

## What changed

- Optional per-identity rate limiting (`GATEWAY_RATE_LIMIT_PER_MINUTE`), keyed
  by API key or client IP; 429 with `Retry-After`; 15 gateway tests.
- HPA 2→4→2 validated on Docker Desktop Kubernetes with metrics-server and a
  mock upstream: 8,000 requests at c=32, 0 errors; CPU 196%/60%; scale-up 45s,
  scale-down 80s.
- 10-minute gateway soak: 11,554 requests, 0 errors, p95 217.39 ms, gauges
  return to 0.
- v0.2.2's TLS terminator, Prometheus alert rules, and OTel/Jaeger tracing
  remain in place.

## Verification at release

- CI: see the repository Actions page for the latest `ci` run.
- Release workflow: tag-triggered; see the Actions page for the `release` run.
- Rate limit: tenant A got 5×200 then 429 with `Retry-After: 59`; tenant B
  remained 200.
- HPA: 2→4 in 45s, 4→2 in 80s; HPA event `SuccessfulRescale New size: 4`.
- Soak: 11,554 requests / 0 errors / p95 217.39 ms.
- Kubernetes gateway evidence: measured on `v0.2.0`; later releases add
  auth/observability/rate-limit features without changing the serving path.

## Deploy

For a registry-based cluster:

```yaml
image: ghcr.io/francisown/8gb-llm-inference-delivery/gateway:v0.2.3
imagePullPolicy: IfNotPresent
```

For the local Docker Desktop/kind path:

```bash
docker pull ghcr.io/francisown/8gb-llm-inference-delivery/gateway:v0.2.3
docker tag ghcr.io/francisown/8gb-llm-inference-delivery/gateway:v0.2.3 \
  ai-inference-gateway:v0.2.3
```

## Do not claim

- The K8s throughput numbers are from v0.2.0, not this exact image.
- HPA and soak results use a mock upstream; they validate gateway mechanics,
  not model performance.
- The self-signed TLS certificate is not public-production ready.
- Jaeger all-in-one uses in-memory storage; traces are not durable.
- No TensorRT-LLM result is included.
