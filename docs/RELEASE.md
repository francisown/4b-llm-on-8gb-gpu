# Release v0.2.2

Release date: **2026-10-21**

- GitHub Release: <https://github.com/francisown/8gb-llm-inference-delivery/releases/tag/v0.2.2>
- Tag: `v0.2.2`
- Image: `ghcr.io/francisown/8gb-llm-inference-delivery/gateway:v0.2.2`
- Digest: `sha256:c1765502e546e61c5fa3a7a968ae0d7e8f1f9cc218ffc0e6396a2d80ca197ded`

## Pull

```bash
docker pull ghcr.io/francisown/8gb-llm-inference-delivery/gateway:v0.2.2
```

The release workflow runs the offline tests, manifest validation, and workflow
validation before publishing. It also requests SBOM and provenance attestations
from BuildKit (`sbom: true`, `provenance: true`).

## What changed

- Local Nginx TLS terminator with a self-signed certificate, HTTPS health/chat
  verification, and production guidance.
- Five Prometheus alert rules: upstream health, error rate, TTFT p95,
  queue-wait p95, and no-successful-requests, with a runbook.
- OpenTelemetry auto-instrumentation and Jaeger OTLP tracing; Grafana gets a
  provisioned Jaeger datasource. OTel is enabled only in the Compose stack;
  the image defaults to `OTEL_SDK_DISABLED=true`.
- v0.2.1's optional `Authorization: Bearer` / `X-API-Key` auth remains in place.

## Verification at release

- CI: successful (run 32).
- Release workflow: successful (run 2); GHCR image pull verified locally.
- TLS: HTTPS `/health` and `/chat` returned 200 through Nginx with a
  self-signed certificate.
- Alert rules: 5 rules loaded in Prometheus.
- OTel: Jaeger received `inference-gateway` traces; first trace had 4 spans;
  no export errors.
- Kubernetes gateway evidence: measured on `v0.2.0`; v0.2.1 added auth and
  v0.2.2 adds deployment/observability layers without changing the serving path.

## Deploy

For a registry-based cluster:

```yaml
image: ghcr.io/francisown/8gb-llm-inference-delivery/gateway:v0.2.2
imagePullPolicy: IfNotPresent
```

For the local Docker Desktop/kind path:

```bash
docker pull ghcr.io/francisown/8gb-llm-inference-delivery/gateway:v0.2.2
docker tag ghcr.io/francisown/8gb-llm-inference-delivery/gateway:v0.2.2 \
  ai-inference-gateway:v0.2.2
```

Rollback within a cluster remains `kubectl rollout undo`; the previous
ReplicaSet is kept by the Deployment.

## Do not claim

- The K8s numbers are not from this exact v0.2.2 image; they were measured on
  v0.2.0.
- No TensorRT-LLM result is included.
- The self-signed certificate is for local validation, not public production.
- Jaeger all-in-one uses in-memory storage; traces are not durable.
