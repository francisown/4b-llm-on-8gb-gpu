# Alerting rules

Prometheus evaluates the rules in
[`deploy/observability/prometheus/alerts.yml`](../deploy/observability/prometheus/alerts.yml).
They cover the gateway layer, not model quality.

## Rules

| Alert | Expression intent | For | Severity |
|---|---|---|---:|---|
| `GatewayUpstreamUnhealthy` | `min(inference_gateway_upstream_healthy) < 1` | 1m | critical |
| `GatewayErrorRateHigh` | timeout/unavailable/upstream/rejected/stream errors > 0.05 req/s | 2m | warning |
| `GatewayTTFTP95High` | TTFT p95 > 300 ms | 5m | warning |
| `GatewayQueueWaitP95High` | queue-wait p95 > 100 ms | 5m | warning |
| `GatewayNoSuccessfulRequests` | traffic exists, success rate is zero | 5m | critical |

## Verify rules are loaded

```bash
curl -s http://localhost:9090/api/v1/rules | jq '.data.groups[].rules[].name'
```

On 2026-10-21 the rules JSON contained one group and five rules:

```text
GatewayUpstreamUnhealthy, GatewayErrorRateHigh, GatewayTTFTP95High,
GatewayQueueWaitP95High, GatewayNoSuccessfulRequests
```

Evidence: [`benchmark/results/observability/prometheus-rules.json`](../benchmark/results/observability/prometheus-rules.json),
[`alertmanager-smoke.txt`](../benchmark/results/observability/alertmanager-smoke.txt), and
[`alertmanager-firing.txt`](../benchmark/results/observability/alertmanager-firing.txt).

The test verified **rule loading**, not a fired page. To exercise an alert,
stop the mock upstream for more than one minute and query
`/api/v1/alerts`; the upstream-health alert should become pending/firing.

## Runbook

- **Upstream unhealthy**: check vLLM `/health`, GPU memory, and the vLLM
  container/pod logs; readiness probes should remove the gateway from Service
  endpoints if the upstream stays down.
- **Error rate high**: split by `outcome`; distinguish 429 (backpressure) from
  5xx/timeouts. Check the gateway admission gauges and upstream latency.
- **TTFT p95 high**: inspect queue wait, vLLM batch size, KV-cache pressure,
  GPU utilization, and thermal/clock state.
- **Queue wait high**: lower `GATEWAY_MAX_CONCURRENT` or add replicas/upstream
  capacity; do not simply increase the queue.
- **No successful requests**: check upstream health, auth configuration, and
  recent deployment/rollback.

## Production notes

- The Compose demo wires Prometheus to a local Alertmanager
  (`prom/alertmanager:v0.28.1`, port 9093) with a null receiver. A temporary
  `GatewaySyntheticRoutingTest` alert fired and appeared in Alertmanager, then
  the rule was removed. This proves end-to-end routing, not external
  notification delivery. Add a Slack/PagerDuty/webhook receiver for paging.
- The thresholds are reference-workload starting points, not universal SLOs.
- The 429 alerts should exclude synthetic load tests; the backpressure test is
  expected to produce 429s.
