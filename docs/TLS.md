# TLS termination for the gateway

## What is implemented

The observability demo includes an Nginx TLS terminator:

- `deploy/observability/nginx/nginx.conf`
- `deploy/observability/generate-certs.sh`
- `deploy/observability/compose.yaml` → `tls-proxy` service, host port `9443`
- self-signed certificate generated into `deploy/observability/nginx/certs/`
  (ignored by Git)

The proxy forwards to `gateway:9000`, sets `X-Forwarded-Proto: https`, and
disables response buffering so SSE still streams.

## Local verification

```bash
bash deploy/observability/generate-certs.sh
docker compose -f deploy/observability/compose.yaml up -d --build
curl -k https://localhost:9443/health
curl -k -X POST https://localhost:9443/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"hello","max_tokens":8}'
```

Observed on 2026-10-21:

- HTTPS `/health` returned 200 with gateway `0.2.4`;
- HTTPS `/chat` returned 200;
- certificate subject/issuer `CN=localhost`, valid for one year;
- Nginx 1.27.5 served the response.

Evidence: [`benchmark/results/observability/tls-smoke.txt`](../benchmark/results/observability/tls-smoke.txt).

## Production guidance

- Do **not** use the self-signed certificate for a public deployment.
- Terminate TLS at a trusted ingress/reverse proxy (Nginx Ingress, Traefik,
  cloud load balancer) with ACME/Let's Encrypt or an organization certificate.
- Never commit private keys. The local `nginx/certs/` directory is ignored.
- Keep TLS 1.2+; the demo disables older protocols.
- Add HSTS only after the certificate and redirect are proven.
- Keep `/metrics` and `/health` on a private network or protect them with
  network policy; API-key auth covers chat endpoints, not metrics.

## Limits

- The demo still exposes the plain HTTP gateway on port 9000 for local
  debugging. Remove that port mapping in a real deployment.
- No client-certificate/mTLS or per-tenant certificate is implemented.
- The TLS proxy is a deployment-layer component; it does not change the
  gateway image or its API contract.
