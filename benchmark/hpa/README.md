# HPA validation (Docker Desktop Kubernetes)

This is a real HPA test, isolated in the `hpa-demo` namespace. It uses a mock
OpenAI-compatible upstream, so it validates **HPA mechanics and CPU-based
scaling**, not vLLM model throughput.

The manifests in this directory pin `ai-inference-gateway:v0.2.2`, the image
used for the recorded run. For a fresh run, retag the current gateway image or
update `gateway.yaml` and `loadgen.yaml` together.

## What it deploys

| Object | Purpose |
|---|---|
| `mock-vllm` Deployment/Service | CPU-light OpenAI-compatible mock upstream |
| `inference-gateway` Deployment/Service | 2 replicas, CPU request 100m, limit 500m |
| `HorizontalPodAutoscaler` | 2–4 replicas, CPU target 60% |
| `gateway-loadgen` Job | 8,000 requests at concurrency 32, max 8 tokens |

The gateway ConfigMap raises admission concurrency to 64 so the load reaches
the CPU rather than being rejected by the default 4+4 limit.

## Run

```bash
kubectl apply -f benchmark/hpa/namespace.yaml

kubectl create configmap mock-vllm-script -n hpa-demo \
  --from-file=mock_vllm.py=deploy/observability/mock_vllm.py \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f benchmark/hpa/mock-vllm.yaml \
  -f benchmark/hpa/gateway.yaml \
  -f benchmark/hpa/hpa.yaml

kubectl wait --for=condition=Available \
  deployment/mock-vllm deployment/inference-gateway \
  -n hpa-demo --timeout=120s

kubectl create configmap loadgen-script -n hpa-demo \
  --from-file=k8s_load_test.py=benchmark/k8s_load_test.py \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f benchmark/hpa/loadgen.yaml
kubectl get hpa -n hpa-demo -w
```

## Observed result (2026-10-21)

| Metric | Result |
|---|---:|
| Initial replicas | 2 |
| Max replicas | 4 |
| CPU target / observed | 60% / **196%** |
| Scale-up | **45 s** (2 → 4) |
| Scale-down | **80 s** (4 → 2, after the 60 s stabilization window) |
| Load | 8,000 requests, concurrency 32, 0 errors |
| Throughput | 158.859 req/s |
| Output tokens/s | 1,270.875 (mock, 8 tokens) |
| Latency p95 | 207.58 ms |

HPA event:

```text
SuccessfulRescale  New size: 4; reason: cpu resource utilization
(percentage of request) above target
```

Evidence: [`../results/hpa/scale-out.txt`](../results/hpa/scale-out.txt) and
[`../results/hpa/summary.json`](../results/hpa/summary.json).

## Limits

- Single-node Docker Desktop cluster; metrics-server is the standard resource
  metrics API, not custom metrics.
- Mock upstream; latency/tokens are not model numbers.
- CPU-based HPA only; no queue-depth or TTFT-based custom metrics.
- The scale-down result depends on the 60 s stabilization window.

## Cleanup

```bash
kubectl delete namespace hpa-demo
```
