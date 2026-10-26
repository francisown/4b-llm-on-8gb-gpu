# Observability demo stack

This Compose stack runs the gateway, a mock OpenAI-compatible upstream,
Prometheus, Grafana, and an optional TLS terminator. It needs **no GPU and no
model weights**.

## Services

| Service | Port | Purpose |
|---|---:|---|
| `gateway` | 9000 | FastAPI gateway (HTTP) |
| `tls-proxy` | 9443 | Nginx HTTPS terminator with a self-signed local certificate |
| `prometheus` | 9090 | Scrapes `gateway:9000/metrics` and evaluates alert rules |
| `grafana` | 3000 | Provisioned Prometheus datasource and `Inference Gateway` dashboard |
| `jaeger` | 16686 / 4318 | Jaeger UI/API and OTLP HTTP trace receiver |
| `mock-vllm` | internal 8000 | Mock OpenAI-compatible upstream; not a model |

## Start

```bash
# Generate a local self-signed cert (ignored by Git)
bash deploy/observability/generate-certs.sh

docker compose -f deploy/observability/compose.yaml up -d --build
```

Open:

- Grafana: <http://localhost:3000> (`admin` / `admin`)
- Jaeger: <http://localhost:16686>
- Prometheus: <http://localhost:9090>
- HTTPS gateway: <https://localhost:9443> (self-signed; use `curl -k`)
- HTTP gateway: <http://localhost:9000>

```bash
curl -k https://localhost:9443/health
curl -k -X POST https://localhost:9443/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"hello","max_tokens":8}'
```

## Stop

```bash
docker compose -f deploy/observability/compose.yaml down
```

## Notes

- The mock upstream exists only to validate the gateway, metrics, dashboard,
  auth, and admission control. It is not a model benchmark.
- The self-signed certificate is for local validation; production should use a
  trusted ingress/ACME certificate.
- Alert rules are in `prometheus/alerts.yml`.
- Traces are exported to Jaeger over OTLP HTTP.
- Current verification summary: [`../../docs/VERIFICATION.md`](../../docs/VERIFICATION.md).
- Certificates are ignored by `.gitignore` under `nginx/certs/`.
