# Queue-depth HPA validation (Docker Desktop Kubernetes)

The CPU HPA in [`../hpa/`](../hpa/) answers "does autoscaling work at all?".
This one answers a harder question: **can the HPA scale on the thing that
actually backs up?** For an I/O-bound gateway, CPU stays flat while requests
queue, so a CPU target either never fires or fires too late.

Here the HPA targets `inference_gateway_waiting_requests`, published by
Prometheus through the Prometheus Adapter as an **External** metric.
`metrics-server` is not involved.

Still a mock upstream on a single node: this validates the autoscaling signal
path, not vLLM throughput or GPU capacity planning.

## What it deploys

Everything lives in `k8s/hpa-queue-demo/` (self-contained kustomize directory):

| Object | Purpose |
|---|---|
| `mock-vllm` Deployment/Service | 150 ms-per-request OpenAI-compatible stub |
| `inference-gateway` Deployment/Service | 2 replicas, `GATEWAY_MAX_CONCURRENT=2`, queue depth 128 |
| `prometheus` | Scrapes each gateway pod every 5 s |
| `prometheus-adapter` | Serves the metric under `external.metrics.k8s.io` |
| `HorizontalPodAutoscaler` | 2–6 replicas, `averageValue: 2` |
| `queue-loadgen` Job | 32 workers for 240 s, **suspended by default** |

The gateway is deliberately narrow (2 admissions per replica, deep queue) so a
modest burst cannot be absorbed and the waiting gauge actually moves.

## Run

```bash
kubectl apply -f k8s/hpa-queue-demo/namespace.yaml
kubectl apply -k k8s/hpa-queue-demo

# the HPA must show a number, not <unknown>
kubectl -n k8s-hpa-queue-demo get hpa
kubectl -n k8s-hpa-queue-demo describe hpa inference-gateway-queue | grep -A3 Conditions

# start load (the Job ships suspended so apply -k never loads the host)
kubectl -n k8s-hpa-queue-demo patch job queue-loadgen --type merge \
  -p '{"spec":{"suspend":false}}'

kubectl -n k8s-hpa-queue-demo get hpa,pods -w
kubectl -n k8s-hpa-queue-demo logs job/queue-loadgen
```

To run it again, the Job has to be recreated (Job specs are largely immutable):

```bash
kubectl -n k8s-hpa-queue-demo delete job queue-loadgen
kubectl apply -k k8s/hpa-queue-demo
```

## Observed result (2026-10-22, v0.2.4)

| Metric | Result |
|---|---:|
| Metric / target | `inference_gateway_waiting_requests` / `averageValue: 2` per pod |
| Load | **12,188 requests**, 32 workers, 240.7 s |
| Non-200 responses | **0** |
| Queue depth peak | 31 |
| Replicas | **2 → 4 → 6 → 5 → 4 → 3 → 2** |
| Scale-up step | +2 pods per 30 s, up to `maxReplicas: 6` |
| Scale-down step | −1 pod per 30 s, after a 120 s stabilization window |

HPA events, in order:

```text
SuccessfulRescale  New size: 4; reason: external metric
                   inference_gateway_waiting_requests(...) above target
SuccessfulRescale  New size: 6; reason: external metric ... above target
SuccessfulRescale  New size: 5; reason: All metrics below target
SuccessfulRescale  New size: 4; reason: All metrics below target
SuccessfulRescale  New size: 3; reason: All metrics below target
SuccessfulRescale  New size: 2; reason: All metrics below target
```

With 6 replicas × 2 admission slots = 12, thirty-two concurrent clients leave
about 20 waiting, so the per-pod average stays above the target and the HPA
holds at the ceiling until load stops.

Evidence: [`../results/k8s-hpa-queue/scale-test.txt`](../results/k8s-hpa-queue/scale-test.txt),
[`../results/k8s-hpa-queue/setup.txt`](../results/k8s-hpa-queue/setup.txt).

## Two traps

Both cost real time and neither is obvious from the error message.

1. The rule must sit under the top-level **`externalRules`** key. Under `rules`
   it is only ever served as a custom metric, and the External APIService
   answers discovery with 404. It must **also** keep
   `resources.overrides.namespace -> namespace`, or the adapter logs
   `no generic resource label form specified for this metric` and never
   resolves the metric.
2. Querying the raw endpoint without a `labelSelector` returns 404 even when
   everything works. The HPA always sends its selector, which is why the HPA
   can be healthy while a bare `kubectl get --raw` is not.

Full write-up: [`docs/HPA_QUEUE.md`](../../docs/HPA_QUEUE.md).

## Limits

- Single-node Docker Desktop cluster.
- Mock upstream; latency and token numbers are not model numbers.
- `averageValue` is an average queue length per gateway pod, not a latency SLO.
- Only the admission queue is used as a signal; TTFT-based and GPU-based
  autoscaling were not tested.
- During scale-down, `kubectl get hpa` reports the old `REPLICAS` value for a
  few tens of seconds while pods are already terminating. Read
  `deployment.spec.replicas` or the pod list when the exact count matters.

## Cleanup

```bash
kubectl delete namespace k8s-hpa-queue-demo
# and remove the cluster-scoped objects the demo created
kubectl delete apiservice v1beta1.external.metrics.k8s.io
kubectl delete clusterrole hpa-queue-prometheus hpa-queue-prometheus-adapter
kubectl delete clusterrolebinding hpa-queue-prometheus hpa-queue-prometheus-adapter \
  hpa-queue-prometheus-adapter-auth-delegator
```

The APIService and the cluster-scoped RBAC are **not** removed by deleting the
namespace. Leaving them behind would break any other adapter installed later,
so clean them up explicitly.
