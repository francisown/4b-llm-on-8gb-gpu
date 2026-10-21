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
[`alertmanager-smoke.txt`](../benchmark/results/observability/alertmanager-smoke.txt),
[`alertmanager-firing.txt`](../benchmark/results/observability/alertmanager-firing.txt), and
[`alertmanager-webhook.txt`](../benchmark/results/observability/alertmanager-webhook.txt).

To exercise a production alert, stop the mock upstream for more than one
minute and query `/api/v1/alerts`; the upstream-health alert should become
pending/firing.

## Webhook delivery

Earlier versions routed alerts to a null receiver. That proved routing but
discarded the notification, so nothing ever left Alertmanager. The demo now
posts to a real HTTP receiver:

- `deploy/observability/compose.yaml` runs a `webhook` service
  (`mendhak/http-https-echo:33`, port 8080).
- `deploy/observability/alertmanager/alertmanager.yml` routes to the
  `local-webhook` receiver at `http://webhook:8080/alert` with
  `send_resolved: true`.

A temporary `GatewaySyntheticRoutingTest` rule (`expr: vector(1)`) produced a
real delivery on both the firing and the resolved transition:

```text
16:44:17Z POST /alert 200 bytes=2636 ua=Alertmanager/0.28.1  status=firing
16:48:46Z POST /alert 200 bytes=2652 ua=Alertmanager/0.28.1  status=resolved
```

A manually injected `ManualProbeTest` alert travelled the same path, which
shows delivery does not depend on Prometheus as the producer. The synthetic
rule was removed afterwards; the five rules above are all that remain.

To re-verify, add a `vector(1)` rule, run `docker compose restart prometheus`,
then read `docker compose logs webhook`.

This proves **local notification delivery**. It does not prove pager delivery:
there is no Slack/PagerDuty/Opsgenie endpoint, no TLS, and no auth on the
webhook hop, which runs on the private compose network.


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
  (`prom/alertmanager:v0.28.1`, port 9093) that posts to a local echo
  container. That is a delivery test, not a paging path. Production needs a
  real receiver over TLS with auth, plus an on-call rotation.
- The thresholds are reference-workload starting points, not universal SLOs.
- The 429 alerts should exclude synthetic load tests; the backpressure test is
  expected to produce 429s.
