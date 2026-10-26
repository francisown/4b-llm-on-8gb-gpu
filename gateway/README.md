# FastAPI inference gateway

The HTTP layer is now a thin adapter around the transport-neutral serving core
in [`../src/llm8g/serving/`](../src/llm8g/serving/). `uvicorn gateway:app` stays
available for existing images and scripts, but the implementation lives in the
package.

This gateway sits between clients and an OpenAI-compatible vLLM server. It is
the stateless service layer of the project; the GPU model server runs outside
the container and, on this host, outside the Kubernetes cluster.

## Layout

| Module | Responsibility |
|---|---|
| `gateway.py` | compatibility shim: `uvicorn gateway:app` imports `llm8g.serving.http` |
| `../src/llm8g/serving/config.py` | validated environment/profile settings |
| `../src/llm8g/serving/service.py` | `GatewayService`: context guard, admission lease, stream lifecycle |
| `../src/llm8g/serving/admission.py` | bounded active/queued admission |
| `../src/llm8g/serving/security.py` | API-key authentication, identity, rate-limit policy |
| `../src/llm8g/serving/upstream.py` | vLLM HTTP/SSE adapter |
| `../src/llm8g/serving/http.py` | FastAPI routes, error mapping, SSE framing, metrics |
| `../tests/test_gateway_http.py` | offline HTTP contract and upstream-fake tests |

## What it implements

- Pydantic request validation and propagation/generation of `X-Request-ID`;
- optional `Authorization: Bearer` / `X-API-Key` authentication for chat
  endpoints; `/live`, `/ready`, `/health`, and `/metrics` stay open for probes
  and Prometheus;
- separate connect/read/write/pool timeouts;
- conversion of upstream connection, timeout, and HTTP errors;
- a dependency-aware `/health` endpoint, a process-only `/live`, and a
  process-local `/ready` used by the Kubernetes readiness probe;
- one reusable asynchronous HTTP connection pool for chat traffic;
- a browser chat UI at `/`, non-streaming `POST /chat`, and SSE streaming
  `POST /chat/stream` with TTFT and total latency;
- a disconnect watcher that closes a stalled upstream after the browser goes
  away, instead of waiting for the next SSE line or the read timeout;
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

## Offline tests

The suite uses a fake vLLM upstream, so it does not require a running model or
GPU. Run it from the repository root:

```bash
python -m pip install -e ".[web,dev]"
python -m pytest -q tests
```

Expected result: **100 passed, 7 skipped** by default (the five skips are the
external C-Eval archive tests); set `CEVAL_ZIP` to the frozen archive and the
same suite runs **107 passed**. `smoke_test.py` remains the separate online test
for a fully running gateway and vLLM server.

## Docker

The image contains only the gateway package. vLLM continues to run separately
with GPU access. Build from the repository root because the package lives in
`src/`:

```bash
docker build -f gateway/Dockerfile -t ai-inference-gateway:stable .
docker compose -f gateway/compose.yaml up -d --build
```

The Dockerfile defaults to `python:3.10-slim` and `https://pypi.org/simple`, so
it builds in a normal CI environment. On a restricted network, override both:

```bash
docker build \
  --build-arg PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.10-slim \
  --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  -f gateway/Dockerfile -t ai-inference-gateway:stable .
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
| `GATEWAY_VERSION` | `stable` | Version exposed in headers/metrics |
| `GATEWAY_API_KEY` | empty (auth disabled) | Optional bearer/X-API-Key token for `/chat` and `/chat/stream`; health/metrics stay open |
| `GATEWAY_API_KEYS` | empty | Optional comma-separated additional keys; useful for per-tenant/per-key limits |
| `GATEWAY_RATE_LIMIT_PER_MINUTE` | `0` (disabled) | Per-identity sliding-window limit; identity is an authenticated API key, otherwise the client IP |
| `GATEWAY_RATE_LIMIT_MAX_IDENTITIES` | `10000` | Bound on the in-memory identity map; new identities share an overflow bucket when full |
| `GATEWAY_RATE_LIMIT_BACKEND` | `process` | `process` for one replica; `redis` for a shared limit across replicas |
| `GATEWAY_REDIS_URL` | `redis://127.0.0.1:6379/0` | Redis URL used when `GATEWAY_RATE_LIMIT_BACKEND=redis` |
| `GATEWAY_AUTH_FAILURE_LIMIT_PER_MINUTE` | `20` | Per-IP limit on failed API-key attempts; `0` disables it |
| `GATEWAY_MAX_CONTEXT_TOKENS` | `2048` | Context window used by the pre-flight length guard; keep in sync with vLLM `--max-model-len` |
| `GATEWAY_TRUST_PROXY_HEADERS` | `0` | Trust `X-Forwarded-For` / `X-Real-IP` for rate-limit identity; enable only behind a proxy that overwrites them |
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
- Admission control is process-local; with N replicas the effective global
  concurrency is roughly `N ×` the configured value. The rate limiter can use
  Redis when a shared budget is required.
- When authentication is disabled, the rate limiter keys on the direct client
  IP. Behind a reverse proxy that IP is the proxy; set
  `GATEWAY_TRUST_PROXY_HEADERS=1` only when that proxy overwrites
  `X-Forwarded-For`/`X-Real-IP`, or enable `GATEWAY_API_KEYS` for per-key
  limits.
- The gateway does not retry read timeouts, because replaying an inference
  request can duplicate work.
