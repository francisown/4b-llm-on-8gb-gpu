# Kubernetes manifests

The deployment boundary is deliberately narrow: Kubernetes runs the stateless
gateway; vLLM runs outside the cluster with GPU access.

## Layout

| Path | Purpose |
|---|---|
| `k8s/` | gateway Deployment, Service, probes, PDB, NetworkPolicy, CPU HPA |
| `k8s/observability/` | Prometheus scrape deployment |
| `k8s/hpa-queue-demo/` | queue-depth HPA with Prometheus Adapter and mock vLLM |
| `k8s/tls-demo/` | Nginx TLS termination and NetworkPolicy with mock vLLM |

The HPA and TLS demos use a mock upstream. They validate gateway mechanics, not
4B-model serving or GPU scheduling.

## Local Docker Desktop

Build the local image and apply the local overlay:

```bash
docker build -f gateway/Dockerfile -t ai-inference-gateway:stable .
kubectl apply -k k8s
kubectl apply -k deploy/k8s-overlays/local
kubectl -n ai-inference rollout status deployment/inference-gateway --timeout=180s
```

The local overlay uses the mutable `stable` tag. The evidence in
[`docs/K8S_VERIFICATION.md`](../docs/K8S_VERIFICATION.md) records the digest of
the exact build tested; rebuilds may produce a different digest.

## Registry image

After publishing a release, use the GHCR overlay instead of the local one:

```bash
kubectl apply -k k8s
kubectl apply -k deploy/k8s-overlays/ghcr
```

The GHCR overlay points at `latest`; pin a digest for a reproducible deployment.

## Smoke test

```bash
kubectl -n ai-inference port-forward svc/inference-gateway 9000:9000
python gateway/smoke_test.py
```

## What is not included

- real 4B vLLM inside Kubernetes;
- GPU device plugin / GPU scheduling;
- multi-node or production TLS certificate management.
