# Service-level objectives (reference workload)

These SLOs apply to the **gateway + vLLM reference deployment**, not to every
possible workload. They are written for the measured environment:

- Qwen3.5-4B-INT4-AWQ-self on one RTX 5060 8 GB;
- vLLM 0.29.0;
- concurrency 4, 256 input / 128 output tokens unless stated otherwise;
- one gateway replica or two replicas behind a Service, as stated.

They are not a production SLA. Change the targets when the model, GPU,
context length, concurrency, or tenant mix changes.

## Objectives

| SLO | Target | Measured reference |
|---|---|---|
| Successful request ratio | **≥ 99.9%** over 30 days | 100/100 and 300/300 in the failure tests |
| TTFT p95 | **< 300 ms** at concurrency 4 | 138.6 ms (streaming) |
| End-to-end p95 | **< 1 s** for 64 output tokens at concurrency 4 | 565.6 ms (stream) / 513.8 ms (non-stream) |
| Gateway error rate | **< 0.5%** | 0% in the load tests |
| Queue wait p95 | **< 100 ms** at nominal load | not independently measured; dashboard exposes it |
| 429 rate | **< 1%** at nominal load | not independently measured; dashboard exposes it |

The measured numbers come from
[`PERFORMANCE_REPORT.md`](PERFORMANCE_REPORT.md) and the raw files under
`benchmark/results/k8s/`.

## PromQL

Use `inference_gateway_*` metrics from `/metrics`.

### Successful request ratio

```promql
sum(rate(inference_gateway_requests_total{outcome="success"}[5m]))
/
sum(rate(inference_gateway_requests_total[5m]))
```

### Error rate

```promql
sum(rate(inference_gateway_requests_total{
  outcome=~"timeout|unavailable|upstream_error|rejected|stream_error|disconnected"
}[5m]))
```

### TTFT p95

```promql
histogram_quantile(
  0.95,
  sum by (le) (rate(inference_gateway_ttft_seconds_bucket[5m]))
)
```

### End-to-end p95

```promql
histogram_quantile(
  0.95,
  sum by (le) (rate(inference_gateway_request_duration_seconds_bucket[5m]))
)
```

### Queue wait p95

```promql
histogram_quantile(
  0.95,
  sum by (le) (rate(inference_gateway_queue_wait_seconds_bucket[5m]))
)
```

### Saturation signals

```promql
inference_gateway_active_requests
inference_gateway_waiting_requests
inference_gateway_upstream_healthy
```

## Error budget policy

- Window: 30 days.
- If 50% of the error budget is consumed in 24 hours, freeze non-essential
  changes and investigate.
- If 100% is consumed, stop feature work; only reliability fixes are allowed
  until the budget recovers.
- A 429 caused by a deliberate load test is not a production error; exclude
  synthetic tests from the budget.

## Dashboard

The Grafana dashboard is provisioned from
[`deploy/observability/grafana/dashboards/gateway-dashboard.json`](../deploy/observability/grafana/dashboards/gateway-dashboard.json).
It shows request rate by outcome, error rate, TTFT p50/p95, end-to-end
p50/p95, queue-wait p95, admission-control gauges, upstream health, completion
tokens/s, and gateway replicas.

Run the CPU-only demo:

```bash
docker compose -f deploy/observability/compose.yaml up -d --build
# Grafana: http://localhost:3000 (admin/admin)
# Prometheus: http://localhost:9090
# Gateway: http://localhost:9000
```

The demo uses a mock OpenAI-compatible upstream. It validates the dashboard and
metric pipeline, not model quality or GPU performance.

## Demo validation (2026-10-21)

The CPU-only Compose stack was started and exercised end to end:

- gateway `/health` returned `{"status":"ok","vllm":"ok","pod":"compose-gateway","version":"0.2.4"}`;
- Prometheus target `inference-gateway` was `up`;
- 20 non-streaming and 5 streaming requests completed successfully and appeared in `inference_gateway_requests_total`;
- Grafana 11.2.0 health was `ok`;
- the provisioned datasource was `Prometheus` (`uid=prometheus`, `url=http://prometheus:9090`);
- the provisioned dashboard was `Inference Gateway` (`uid=inference-gateway`).
- HTTPS `/health` through the Nginx TLS terminator returned 200 for gateway
  `0.2.4`; HTTPS `/chat` returned 200.
- Prometheus loaded five alert rules (`GatewayUpstreamUnhealthy`,
  `GatewayErrorRateHigh`, `GatewayTTFTP95High`, `GatewayQueueWaitP95High`,
  `GatewayNoSuccessfulRequests`).
- Alertmanager was ready on 9093 and Prometheus reported it as an active
  Alertmanager (null receiver; routing connectivity only).
- Jaeger received traces from `inference-gateway`: 5 traces, first trace
  4 spans, no OTel export errors.

### Soak validation

A v0.2.4 2-minute closed-loop soak at concurrency 4 completed **2,329 requests with 0
errors**, 19.389 req/s, p95 **215.82 ms**, and `active=0`, `waiting=0` after a
one-second drain. A v0.2.4 10-minute soak completed **11,717 requests with 0
errors**, 19.525 req/s, p95 **213.62 ms**, and the same gauge recovery. A
v0.2.4 2-hour soak completed **140,178 requests with 0 errors**, 19.469 req/s,
p95 **214.82 ms**, p99 220.03 ms, with `active=0`, `waiting=0` after drain. A
**real-vLLM** 10-minute soak completed **5,992 requests with 0 errors**,
9.986 req/s, p95 **418.49 ms**, p99 538.67 ms, with the same gauge recovery. A
A 2-hour real-vLLM soak completed **67,530 requests with 0 errors**, 9.379
req/s, p95 **458.12 ms**, p99 639.09 ms, gauges 0; the earlier 30-minute run
on the same setup did 17,609 requests at 9.781 req/s with p95 433.79 ms. A
concurrency-16 backpressure run produced 621 successes and 6,544 clean 429s with
**0 other errors**. These are gateway-stability tests; the first three use the
mock upstream, the real-vLLM soak uses the model server. Evidence:
[`soak-c4-120s-v0.2.4.json`](../benchmark/results/observability/soak-c4-120s-v0.2.4.json),
[`soak-c4-600s-v0.2.4.json`](../benchmark/results/observability/soak-c4-600s-v0.2.4.json),
[`soak-c4-7200s-v0.2.4.json`](../benchmark/results/observability/soak-c4-7200s-v0.2.4.json),
[`real-vllm-docker-soak-c4-600s.json`](../benchmark/results/real-vllm-docker-soak-c4-600s.json),
[`real-vllm-docker-soak-c4-1800s.json`](../benchmark/results/real-vllm-docker-soak-c4-1800s.json),
[`real-vllm-docker-soak-c4-7200s.json`](../benchmark/results/real-vllm-docker-soak-c4-7200s.json),
[`backpressure-c16-30s.json`](../benchmark/results/observability/backpressure-c16-30s.json).

Evidence: [`benchmark/results/observability/summary.txt`](../benchmark/results/observability/summary.txt),
[`prometheus-targets.json`](../benchmark/results/observability/prometheus-targets.json),
[`prometheus-requests.json`](../benchmark/results/observability/prometheus-requests.json),
[`grafana-dashboard-api.json`](../benchmark/results/observability/grafana-dashboard-api.json).

## Limits

- Single GPU, single model server; the model server is a single point of failure.
- The K8s base manifests do not terminate TLS or require API keys; the Compose
  demo adds TLS/auth. There is no per-tenant isolation or shared quota store.
- No multi-hour GPU/K8s soak. The 2-hour soak uses the mock upstream; the
  real-vLLM soak is 10 minutes. The error budget is a policy template, not a
  measured 30-day history.
- The SLO targets are for the stated reference workload only.
