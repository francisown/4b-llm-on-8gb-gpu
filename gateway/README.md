# FastAPI inference gateway

This gateway sits between clients and an OpenAI-compatible vLLM server. It is
the stateless service layer of the project; the GPU model server runs outside
the container and, on this host, outside the Kubernetes cluster.

## What it implements

- Pydantic request validation and propagation/generation of `X-Request-ID`;
- optional `Authorization: Bearer` / `X-API-Key` authentication for chat endpoints;
  `/live`, `/health`, and `/metrics` stay open for probes and Prometheus;
- separate connect/read/write/pool timeouts;
- conversion of upstream connection, timeout, and HTTP errors;
- a dependency-aware `/health` endpoint and a process-only `/live` endpoint;
- one reusable asynchronous HTTP connection pool for chat traffic;
- a browser chat UI at `/`, non-streaming `POST /chat`, and SSE streaming
  `POST /chat/stream` with TTFT and total latency;
- upstream cancellation when the browser disconnects;
- bounded admission control with active/queued counters and HTTP 429
  backpressure;
- a `/gateway/status` endpoint for observing active and waiting requests;
- Prometheus counters, gauges, and latency histograms at `/metrics`;
- `X-Gateway-Pod` and `X-Gateway-Version` on every response, so a load test can
  prove which replica served a request;
- single-line JSON logs with request ID, outcome, queue wait, TTFT/E2E latency,
  status code, and error type;
- connect-only upstream retry: a failed pre-send connection is retried, a read
  timeout is never replayed;
- health checks that send `Connection: close` and disable keep-alive reuse.

The last item came from a real Kubernetes failure: reusing a keep-alive
connection to vLLM produced intermittent `RemoteProtocolError` health failures
even though the pod stayed Ready. The regression test asserts the
`Connection: close` header.

Authentication is implemented in the image. TLS termination and the external
Prometheus/Grafana stack remain deployment-layer components.

## Offline tests

The pytest suite uses a fake vLLM upstream, so it does not require a running
model or GPU:

```bash
cd gateway
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Expected result: **19 passed**. `smoke_test.py` remains the separate online test
for a fully running gateway and vLLM server.

## Docker

The image contains only the FastAPI gateway. vLLM continues to run separately
with GPU access. Start vLLM on port 8000 before testing `/health` or chat.

The Dockerfile defaults to `python:3.10-slim` and `https://pypi.org/simple`, so
it builds in a normal CI environment. On a restricted network, override both:

```bash
docker build \
  --build-arg PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.10-slim \
  --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  -t ai-inference-gateway:v0.2.4 .
```

```bash
docker compose up -d --build
docker compose ps
curl -s http://127.0.0.1:9000/live
curl -s http://127.0.0.1:9000/health
docker compose logs -f gateway
```

Open `http://localhost:9000/` to test the browser chat UI. `/live` checks only
the gateway process; `/health` also checks the upstream vLLM service.

The Compose `extra_hosts` entry maps `host.docker.internal` to the Docker host,
allowing the container to reach vLLM on port 8000. If that route changes, set
`VLLM_BASE_URL` explicitly.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `VLLM_BASE_URL` | `http://127.0.0.1:8000` | OpenAI-compatible upstream |
| `MODEL_NAME` | `Qwen3.5-4B-INT4-AWQ-self` | Served model name |
| `UPSTREAM_TIMEOUT_SECONDS` | `60` | Chat read timeout |
| `HEALTH_TIMEOUT_SECONDS` | `3` | `/health` upstream timeout |
| `UPSTREAM_CONNECT_RETRIES` | `1` | Retries for pre-send connection failures |
| `GATEWAY_MAX_CONCURRENT` | `4` | Active requests admitted to vLLM |
| `GATEWAY_MAX_QUEUE` | `4` | Additional requests allowed to wait |
| `GATEWAY_QUEUE_TIMEOUT_SECONDS` | `10` | Maximum queue wait before 429 |
| `GATEWAY_VERSION` | `0.2.4` | Version exposed in headers/metrics |
| `GATEWAY_API_KEY` | empty (auth disabled) | Optional bearer/X-API-Key token for `/chat` and `/chat/stream`; health/metrics stay open |
| `GATEWAY_API_KEYS` | empty | Optional comma-separated additional keys; useful for per-tenant/per-key limits |
| `GATEWAY_RATE_LIMIT_PER_MINUTE` | `0` (disabled) | Per-identity sliding-window limit; identity is an authenticated API key, otherwise the direct client IP |
| `GATEWAY_RATE_LIMIT_MAX_IDENTITIES` | `10000` | Bound on the in-memory identity map; new identities share an overflow bucket when full |
| `POD_NAME` | `local` | Pod identity; set from `metadata.name` in Kubernetes |
| `LOG_LEVEL` | `INFO` | Application log level |

## Kubernetes

The gateway is deployed as two replicas with `maxUnavailable: 0`, a PDB,
`/health` readiness, per-pod Prometheus scraping, and graceful shutdown. The
full evidence is in [`../docs/K8S_VERIFICATION.md`](../docs/K8S_VERIFICATION.md).

## Limitations

- This reference stack has no TLS termination, per-tenant quota, or shared
  rate-limit store. TLS is provided by the Compose Nginx layer, not by the
  gateway image itself.
- Admission control and rate limiting are process-local; with N replicas the
  effective global concurrency/limit is roughly `N ×` the configured value.
- When authentication is disabled, the rate limiter keys on the direct client
  IP. Behind a reverse proxy that IP is the proxy, so enable `GATEWAY_API_KEYS`
  for real per-key limits rather than relying on forwarded headers.
- The gateway does not retry read timeouts, because replaying an inference
  request can duplicate work.
