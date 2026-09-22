# FastAPI inference gateway

This gateway sits between clients and the local vLLM OpenAI-compatible server.

It currently demonstrates:

- Pydantic request validation;
- propagation or generation of `X-Request-ID`;
- separate connect/read/write/pool timeouts;
- conversion of upstream connection, timeout, and HTTP errors;
- a dependency-aware `/health` endpoint;
- one reusable asynchronous HTTP connection pool.
- a browser chat UI at `/` with short client-side conversation history;
- non-streaming chat at `POST /chat`;
- SSE token streaming at `POST /chat/stream`, including TTFT and total latency;
- upstream cancellation when the browser disconnects.
- bounded admission control with active/queued counters and HTTP 429 backpressure;
- a `/gateway/status` endpoint for observing active and waiting requests.
- Prometheus counters, gauges, and latency histograms at `/metrics`.
- separate `/live` (process) and `/health` (vLLM dependency) probes;
- a non-root Docker image and Compose configuration for the gateway.
- single-line JSON application logs with request ID, outcome, queue wait,
  TTFT/E2E latency, status code, and error type when applicable;
- offline pytest coverage for success, validation, upstream timeout/disconnect,
  upstream HTTP errors, capacity rejection, and queue timeout.

Authentication and an external Prometheus/Grafana deployment remain outside
this gateway image.

## Offline tests

The pytest suite uses a fake vLLM upstream, so it does not require a running
model or GPU:

```bash
cd /mnt/e/AI-Inference-Lab/gateway
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Expected result: `9 passed`. `smoke_test.py` remains the separate online test
for a fully running gateway and vLLM server.

## Docker

The image contains only the FastAPI gateway. vLLM continues to run separately
on the WSL GPU host. Start vLLM on port 8000 before testing `/health` or chat.

The Dockerfile uses a Docker Hub mirror for the Python base image and the
Tsinghua PyPI mirror because direct access to Docker Hub and Python package
files timed out on this machine.

```bash
cd /mnt/e/AI-Inference-Lab/gateway
docker compose up -d --build
docker compose ps
curl -s http://127.0.0.1:9000/live
curl -s http://127.0.0.1:9000/health
docker compose logs -f gateway
```

Open `http://localhost:9000/` in Windows to test the browser chat UI. `/live`
checks only the gateway process; `/health` also checks the upstream vLLM
service.

Stop and restart the gateway with:

```bash
docker compose down
docker compose up -d
```

Stop any locally running Uvicorn process before publishing container port 9000.
The Compose `extra_hosts` entry maps `host.docker.internal` to the WSL Docker
host, allowing the container to reach vLLM on port 8000. If that route changes,
set `VLLM_BASE_URL` explicitly before running Compose.
