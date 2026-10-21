# OpenTelemetry tracing

The observability demo sends traces from the gateway to Jaeger. Metrics remain
on Prometheus; logs remain single-line JSON on stdout. This closes the
metrics/traces/logs triad for the demo stack.

## Components

| Component | Port | Purpose |
|---|---:|---|
| `jaeger` | 16686 | Jaeger UI/API |
| `jaeger` | 4318 | OTLP HTTP receiver |
| `gateway` | 9000 | Auto-instrumented FastAPI + httpx client |

The gateway image runs:

```text
opentelemetry-instrument uvicorn gateway:app ...
```

The image sets `OTEL_SDK_DISABLED=true` by default, so standalone/K8s runs do
not try to export to a nonexistent collector. The observability Compose stack
overrides it.

## Enable in Compose

`deploy/observability/compose.yaml` sets:

```yaml
OTEL_SDK_DISABLED: "false"
OTEL_SERVICE_NAME: inference-gateway
OTEL_EXPORTER_OTLP_ENDPOINT: http://jaeger:4318
OTEL_EXPORTER_OTLP_PROTOCOL: http/protobuf
OTEL_TRACES_EXPORTER: otlp
OTEL_METRICS_EXPORTER: none
OTEL_LOGS_EXPORTER: none
```

Grafana is provisioned with a Jaeger datasource (`uid=jaeger`,
`url=http://jaeger:16686`).

## Verify

```bash
docker compose -f deploy/observability/compose.yaml up -d --build
for i in 1 2 3 4 5; do
  curl -k -sS -X POST https://localhost:9443/chat \
    -H 'Content-Type: application/json' \
    -d '{"message":"otel smoke","max_tokens":8}' > /dev/null
done
curl -s http://localhost:16686/api/services
curl -s 'http://localhost:16686/api/traces?service=inference-gateway&limit=5'
```

Observed on 2026-10-21:

- `api/services` returned `inference-gateway`;
- `api/traces` returned 5 traces;
- the first trace had 4 spans;
- gateway logs had no OTel export errors.

Evidence:
[`benchmark/results/observability/otel-smoke.txt`](../benchmark/results/observability/otel-smoke.txt),
[`jaeger-services.json`](../benchmark/results/observability/jaeger-services.json),
[`jaeger-traces.json`](../benchmark/results/observability/jaeger-traces.json).

## Limits

- Jaeger all-in-one uses in-memory storage; traces are lost on restart.
- No sampling policy or tail sampling is configured; the demo exports all
  traces. Add a Collector for production sampling and routing.
- No trace-to-log correlation IDs are injected into the JSON logs.
- The Kubernetes Deployment does not enable OTel; set the same env vars and
  deploy a Collector/backend before enabling it there.
- Auto-instrumentation is a demo convenience; a production setup should pin
  instrumentation versions and verify span attributes against the service
  contract.

## Production path

1. Deploy an OpenTelemetry Collector (DaemonSet or gateway).
2. Send OTLP to the Collector; export to Tempo/Jaeger with persistent storage.
3. Configure head/tail sampling and resource attributes.
4. Add Grafana trace datasource and trace-to-logs links.
5. Set SLOs on trace-derived latency only after the sampling policy is stable.
