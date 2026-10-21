# Queue-depth HPA on Kubernetes

CPU-based autoscaling is the wrong signal for this gateway. It is I/O bound:
under load the process waits on the upstream, so CPU stays flat while requests
pile up in the admission queue. This demo scales on the queue depth instead.

`k8s/hpa-queue-demo/` deploys a mock upstream, two gateway replicas, an
in-cluster Prometheus, a Prometheus Adapter, and an HPA that targets
`inference_gateway_waiting_requests` through the External metrics API.

## Layout

| File | Contents |
|---|---|
| `namespace.yaml` | `k8s-hpa-queue-demo` namespace |
| `mock-vllm.yaml` | OpenAI-compatible stub (150 ms per request) |
| `gateway.yaml` | 2 replicas, `GATEWAY_MAX_CONCURRENT=2`, queue depth 128 |
| `prometheus.yaml` | Scrapes each gateway pod every 5 s |
| `adapter.yaml` | Prometheus Adapter + External APIService + RBAC |
| `hpa.yaml` | HPA v2 on the external queue-depth metric, 2–6 replicas |
| `loadgen-job.yaml` | In-cluster load generator, **suspended by default** |

The gateway is deliberately narrow: two concurrent admissions per replica with
a deep queue, so a modest burst cannot be absorbed and the waiting gauge
actually moves.

## Deploy

```bash
kubectl apply -f k8s/hpa-queue-demo/namespace.yaml
kubectl apply -k k8s/hpa-queue-demo
kubectl -n k8s-hpa-queue-demo get hpa
```

The HPA should show a number, not `<unknown>`:

```text
NAME                      REFERENCE                TARGETS   MINPODS   MAXPODS   REPLICAS
inference-gateway-queue   Deployment/inference-gateway   0/2 (avg)   2   6   2
```

`ScalingActive=True / ValidMetricFound` in `describe hpa` is the condition that
matters. A `<unknown>` target there means the adapter is not answering.

## Two traps worth knowing

Both of these cost real time to find, and neither is obvious from the error
message alone.

### 1. External metrics need `externalRules`, not `rules`

Putting a rule under the top-level `rules` key makes it a **custom** metric no
matter what else you do. The `external.metrics.k8s.io` APIService then answers
discovery with 404 and the HPA reports `<unknown>`:

```text
failing or missing response from https://.../apis/external.metrics.k8s.io/v1beta1: 404
```

Adding `resources.overrides` under `rules` makes it worse: the metric becomes a
custom metric on the `namespaces` resource, which is not what the HPA External
block asks for.

The working shape is `externalRules` **plus** a namespace override. Both are
required:

```yaml
rules: []
externalRules:
  - seriesQuery: 'inference_gateway_waiting_requests{namespace!=""}'
    resources:
      overrides:
        namespace:
          resource: namespace
    name:
      matches: '^inference_gateway_waiting_requests$'
      as: 'inference_gateway_waiting_requests'
    metricsQuery: 'sum(<<.Series>>{<<.LabelMatchers>>}) by (namespace)'
```

Drop the override and the adapter logs, once per discovery interval:

```text
unable to generate a query for the metric: unable to convert resource
namespaces into label: no generic resource label form specified for this metric
```

### 2. The raw API needs a `labelSelector`

Querying the external metric without a selector returns 404 even when
everything is healthy:

```bash
# 404
kubectl get --raw /apis/external.metrics.k8s.io/v1beta1/namespaces/k8s-hpa-queue-demo/inference_gateway_waiting_requests

# works
kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1/namespaces/k8s-hpa-queue-demo/inference_gateway_waiting_requests?labelSelector=namespace%3Dk8s-hpa-queue-demo"
```

```json
{"kind":"ExternalMetricValueList","items":[
  {"metricName":"inference_gateway_waiting_requests",
   "metricLabels":{"namespace":"k8s-hpa-queue-demo"},"value":"0"}]}
```

The HPA always sends its selector, which is why the HPA works while a bare
`kubectl get --raw` does not.

## Run the scale test

The Job is suspended so `kubectl apply -k` never starts load on its own:

```bash
kubectl -n k8s-hpa-queue-demo patch job queue-loadgen --type merge \
  -p '{"spec":{"suspend":false}}'
kubectl -n k8s-hpa-queue-demo get hpa,pods -w
```

Delete and re-apply the Job to run it again (Job specs are mostly immutable).

## Result

Observed on 2026-10-22 with a short smoke-scale run: 8 concurrent clients for
30 s through a port-forward, 310 requests, all `200`. The point is the signal
path, not peak throughput.

| Phase | Queue depth | HPA readout | Replicas |
|---|---:|---|---:|
| Idle | 0 | `0/2` | 2 |
| Under load | 6 | `2/2` | 2 → 3 |
| After load | 0 | `0/2` | 3 → 2 |

Eight concurrent clients against a capacity of 2 per replica × 2 replicas
leaves 6 waiting, so the per-pod average lands at 3 against a target of 2.
Two `SuccessfulRescale` events followed, in order:

```text
New size: 3; reason: external metric inference_gateway_waiting_requests(...) above target
New size: 2; reason: All metrics below target
```

The scale-down waited out the 120 s stabilization window before dropping a
pod, which is the intended behaviour: a short burst should not shrink the pool
underneath in-flight work.

Evidence: [`scale-test.txt`](../benchmark/results/k8s-hpa-queue/scale-test.txt),
[`setup.txt`](../benchmark/results/k8s-hpa-queue/setup.txt).

## Not claimed

- This scales the **gateway** on its admission queue with a **mock** upstream.
  It is not vLLM or GPU autoscaling, and it says nothing about model latency.
- The upstream is a fixed-capacity stub; adding gateway replicas raises the
  request rate against it but does not make the model faster.
- Single-node Docker Desktop cluster; no multi-node scheduling or bin-packing
  behaviour is exercised.
- `AverageValue` is an average queue length per gateway pod, not a latency SLO.
