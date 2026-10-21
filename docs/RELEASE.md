# Release v0.2.1

Release date: **2026-10-21**

- GitHub Release: <https://github.com/francisown/8gb-llm-inference-delivery/releases/tag/v0.2.1>
- Tag: `v0.2.1`
- Image: `ghcr.io/francisown/8gb-llm-inference-delivery/gateway:v0.2.1`
- Digest: `sha256:908a6feacaa8ed1f4e10056102f006bb008930fffa1f4a93ef6ba05f45450ac0`

## Pull

```bash
docker pull ghcr.io/francisown/8gb-llm-inference-delivery/gateway:v0.2.1
```

The release workflow runs the offline tests, manifest validation, and workflow
validation before publishing. It also requests SBOM and provenance attestations
from BuildKit (`sbom: true`, `provenance: true`).

## What changed

- Optional `Authorization: Bearer` / `X-API-Key` authentication for
  `/chat` and `/chat/stream`; `/live`, `/health`, and `/metrics` remain open
  for probes and Prometheus.
- `inference_gateway_auth_failures_total` metric and two auth regression tests
  (14 gateway tests total).
- CPU-only Compose observability stack with mock vLLM, Prometheus, and a
  provisioned Grafana dashboard.
- SLO/error-budget documentation, release checklist, and tag-triggered GHCR
  release workflow.
- Repeatable gateway soak and concurrency-16 backpressure evidence.
- Scope cleanup: unrelated financial research and career files removed; the
  inference-ops agent moved to `experiments/inference-ops-agent/`.

## Verification at release

- CI: successful (run 28).
- Release workflow: successful (run 1); GHCR image pull verified locally.
- Kubernetes gateway evidence: measured on `v0.2.0`; v0.2.1 adds auth and a
  versioned image tag without changing the serving path.
- Gateway soak: 2,329 requests / 0 errors / p95 216.64 ms (mock upstream,
  v0.2.0).
- Backpressure: 6,544 clean 429s / 0 other errors at c=16 (mock upstream,
  v0.2.0).

## Deploy

For a registry-based cluster, use the GHCR image directly:

```yaml
image: ghcr.io/francisown/8gb-llm-inference-delivery/gateway:v0.2.1
imagePullPolicy: IfNotPresent
```

For the local Docker Desktop/kind path, pull or import the image under the
same name:

```bash
docker pull ghcr.io/francisown/8gb-llm-inference-delivery/gateway:v0.2.1
docker tag ghcr.io/francisown/8gb-llm-inference-delivery/gateway:v0.2.1 \
  ai-inference-gateway:v0.2.1
```

Rollback within a cluster remains `kubectl rollout undo`; the previous
ReplicaSet is kept by the Deployment.

## Do not claim

- The K8s numbers are not from this exact v0.2.1 image; they were measured on
  v0.2.0 before the auth change.
- No TensorRT-LLM result is included.
- The GHCR image is public, but no production SLA or multi-tenant security
  review is implied.
