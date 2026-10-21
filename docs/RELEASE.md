# Release v0.2.4

Release date: **2026-10-21**

- GitHub Release: <https://github.com/francisown/8gb-llm-inference-delivery/releases/tag/v0.2.4>
- Tag: `v0.2.4`
- Image: `ghcr.io/francisown/8gb-llm-inference-delivery/gateway:v0.2.4`
- Digest: `sha256:4453ef462ac426b6abe239819d41a4171454f7ebffacaf90ffb481a8f95e1365`

## Pull

```bash
docker pull ghcr.io/francisown/8gb-llm-inference-delivery/gateway:v0.2.4
```

## What changed

- Rate limiting now trusts the API key as an identity only when auth is
  configured; with auth disabled it uses the direct client IP, so rotating
  arbitrary `X-API-Key` headers no longer creates new buckets.
- The rate-limit identity map is bounded
  (`GATEWAY_RATE_LIMIT_MAX_IDENTITIES`); new identities share an overflow bucket
  when it is full.
- `GATEWAY_API_KEYS` accepts multiple comma-separated authenticated keys for
  per-key limits.
- Malformed upstream JSON now returns `502` with a structured log/metric instead
  of an unhandled `500`.
- Gateway tests: 19, including window expiry, bounded identity map,
  auth + rate-limit interaction, and malformed upstream responses.
- The quantization CSV is regenerated from raw evidence and checked in CI.
- HPA documentation now matches the separate `hpa-demo` validation.
- CI checks Markdown links and the generated CSV; future release bodies use this
  file.

## Verification

- Deterministic path: `python scripts/verify_local.py` (5 cost + 19 gateway
  tests), manifest validation (17 documents), workflow validation, docs
  validation, generated-CSV check.
- v0.2.4 2-minute mock soak: 2,329 requests, 0 errors, p95 215.82 ms.
- v0.2.4 10-minute mock soak: 11,717 requests, 0 errors, 19.525 req/s,
  p95 213.62 ms.
- HPA re-run on v0.2.4 with CPU metrics + mock upstream: 2→4 in 45 s,
  4→2 in 90 s, 8,000 requests at c=32 with 0 errors, CPU 198%/60%.
- Rate limit on v0.2.4: auth disabled, rotating `X-API-Key` no longer creates a
  new bucket (same direct IP); auth enabled, tenant A 5×200 then 429 while
  tenant B remains 200.
- HPA and soak results use a mock upstream; they validate gateway mechanics,
  not model throughput.
- CI: runs 38, 39, 40, and 41 succeeded.
- Release workflow: run 4 succeeded; GitHub Release published
  `2026-10-21T06:01:37Z`.
- GHCR: `docker pull ...:v0.2.4` succeeded; digest
  `sha256:4453ef462ac426b6abe239819d41a4171454f7ebffacaf90ffb481a8f95e1365`;
  the pulled image reports `GATEWAY_VERSION=0.2.4`.

## Deploy

For a registry-based cluster:

```yaml
image: ghcr.io/francisown/8gb-llm-inference-delivery/gateway:v0.2.4
imagePullPolicy: IfNotPresent
```

For the local Docker Desktop/kind path:

```bash
docker pull ghcr.io/francisown/8gb-llm-inference-delivery/gateway:v0.2.4
docker tag ghcr.io/francisown/8gb-llm-inference-delivery/gateway:v0.2.4 \
  ai-inference-gateway:v0.2.4
```

## Do not claim

- The K8s throughput numbers were measured on v0.2.0; later releases add
  gateway features without changing the serving path.
- HPA and soak results use a mock upstream; they validate gateway mechanics,
  not model performance.
- The self-signed TLS certificate is not public-production ready.
- Jaeger all-in-one uses in-memory storage; traces are not durable.
- The 7.49 GiB offline bundle is local and not published.
- No TensorRT-LLM result is included.
