# Architecture

This repository is a capability-oriented inference delivery path:

```text
model input -> quantized artifact -> quality evidence -> performance evidence
             -> vLLM serving -> FastAPI gateway -> Docker/Kubernetes
```

The unit of delivery is a **release**, not a script or a container. A release
must answer: which model/artifact is running, what changed, on what protocol and
hardware it was measured, and how the same configuration is restarted.

## Layout

```text
src/llm8g/
  serving/
    config.py        # validated GatewaySettings
    models.py        # ChatRequest, ChatResult, StreamEvent, TokenUsage
    ports.py         # InferenceBackend contract
    service.py       # GatewayService
    admission.py     # bounded active/queued work
    limits.py        # process-local sliding-window limiter
    redis_limits.py  # optional shared limiter
    security.py      # API-key auth and identity policy
    upstream.py      # vLLM HTTP/SSE adapter
    http.py          # ~120-line composition root
    routes.py        # FastAPI routes and SSE
    transport.py     # request IDs, error mapping, disconnect cleanup
    dependencies.py  # auth / rate-limit dependency
    metrics.py       # per-app ServingMetrics + CollectorRegistry
    schemas.py       # HTTP request/response schemas
    logging.py       # JSON logs
  evaluation/        # C-Eval, quant quality, scoring, stats
  quantization/      # FP8 / INT4-AWQ CLIs and artifact manifests
  benchmarking/      # protocol, runner, stats, cost
  cli.py             # serving CLI

gateway/             # uvicorn gateway:app shim, Dockerfile, Compose
configs/             # serving profiles and benchmark protocol
deploy/              # observability and K8s overlays
k8s/                 # deployment, HPA, NetworkPolicy, TLS demo
benchmark/           # soak/load runners and current evidence
tests/               # unit, HTTP contract, evaluation, metrics, CLI
```

## Serving seam

`GatewayService` owns request validation, admission lease, and stream lifecycle.
`InferenceBackend` owns model execution. HTTP does not know vLLM internals; vLLM
does not know HTTP status codes or Prometheus.

`InferenceBackend` requires:

```python
async def start() -> None
async def close() -> None
async def complete(request, *, request_id) -> (answer, usage, model)
def stream(request, *, request_id) -> AsyncIterator[StreamEvent]
async def open_stream(request, *, request_id) -> AsyncIterator[StreamEvent]
async def health() -> bool
```

`open_stream` is eager: upstream connection errors and HTTP errors can be
translated before SSE headers are sent. `GatewayService` releases the admission
lease if opening fails.

## Evaluation seam

```text
DatasetManifest -> ModelRunner -> CaseResult[] -> Report
```

C-Eval, free-form cases, and local quant-quality cases are dataset adapters.
vLLM HTTP and local Transformers are runner adapters. Scoring and paired
statistics are pure functions.

## Quantization seam

`ModelSpec` + `CalibrationManifest` -> quantized artifact + `ArtifactManifest`.
The artifact manifest records input model, calibration hash, algorithm/version,
file list/size, and runnability checks. `llm-compressor` is an adapter; the
project does not reimplement AWQ/FP8 algorithms.

## Benchmark seam

`BenchmarkProtocol` carries runtime, GPU, model, input/output tokens,
concurrency, repetitions, temperature, and thinking mode. `BenchmarkResult`
carries the protocol, throughput, TTFT/TPOT, error rate, raw path, and metadata.
Results with different protocols are not merged.

## Compatibility

`gateway/gateway.py` keeps `uvicorn gateway:app`, existing HTTP paths, and
environment-variable names working. Root quantization/evaluation scripts are
compatibility wrappers around `src/llm8g`.

## Deployment boundary

Docker/Kubernetes run the stateless gateway. vLLM runs outside the gateway
container with GPU access. HPA and TLS demos use a mock vLLM; they validate
gateway mechanics, not model performance.
