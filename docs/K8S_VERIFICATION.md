# Kubernetes verification

Verified on 2026-10-26 on Docker Desktop Kubernetes `v1.36.1` with
`ai-inference-gateway:stable` (digest `sha256:b3bd991c...`). The base ConfigMap
points at `host.docker.internal:8000`; this smoke used the in-cluster
`mock-vllm` service, as do the HPA/TLS demos.

## Gateway layer

- namespace: `ai-inference`
- 2 replicas, `maxUnavailable: 0`, `maxSurge: 1`
- startup `/live`, readiness `/ready`, liveness `/live`
- `/health` checks the vLLM dependency
- PDB, NetworkPolicy, HPA, Prometheus annotations present
- image: `ai-inference-gateway:stable`, digest `sha256:b3bd991c...`

Result:

- 2/2 Ready;
- `/live`, `/ready`, `/health`, `/chat`, `/chat/stream`, `/metrics` pass via
  `gateway/smoke_test.py`;
- rolling restart returns to 2/2;
- deleting both gateway pods returns to 2/2 and smoke passes again.

Evidence: [`benchmark/results/k8s-smoke.json`](../benchmark/results/k8s-smoke.json).

## HPA

The queue-depth HPA uses `inference_gateway_waiting_requests` from the
Prometheus Adapter, min 2 / max 6. Load generator: 32 workers, 240 s, mock
vLLM.

Observed:

| Phase | Replicas |
|---|---|
| start | 2 |
| ~20 s | 4 |
| ~50 s | 6 |
| load removed | 6 → 5 → 4 → 3 → 2 |

The HPA run uses the in-cluster mock upstream, not the 4B model. The HPA/TLS
mechanics were recorded with the pre-rebuild stable image; the current gateway
smoke digest is in `k8s-smoke.json`.

Evidence: [`benchmark/results/k8s-hpa-tls.json`](../benchmark/results/k8s-hpa-tls.json).

## TLS demo

`k8s/tls-demo` terminates TLS at an Nginx proxy and enforces an ingress
NetworkPolicy.

Result with the final image:

- HTTPS `/live`: 200
- HTTPS `/health`: 200

The TLS run also uses the in-cluster mock upstream.

## Not verified

- real 4B vLLM inside Kubernetes;
- GPU device plugin / GPU-in-K8s scheduling;
- multi-node cluster;
- production TLS certificate management.
