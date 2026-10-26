# Changelog

## Initial release

- `src/llm8g` is the canonical implementation for serving, evaluation,
  quantization, and benchmarking.
- `GatewayService` / `InferenceBackend` seam with explicit `start`, `close`,
  `complete`, `stream`, `open_stream`, and `health`.
- FastAPI split into `http.py`, `routes.py`, `transport.py`,
  `dependencies.py`; `http.py` is a ~120-line composition root.
- Per-app `ServingMetrics` and CollectorRegistry; `/metrics` no longer depends
  on process-global metric state.
- Optional API-key UI, request-ID sanitization, metric outcome semantics,
  periodic limiter cleanup, and Redis limiter adapter.
- Small FastAPI/HTTP error paths covered by contract tests.
- Evaluation HTTP/reporting helpers extracted; compatibility wrappers retained.
- Lazy quantization imports so `--help` works without the GPU stack.
- Docker image built from a frozen `gateway/requirements-image.lock.txt`, then
  installed with `--no-deps`.
- Release workflow added for manual GHCR builds with SBOM and provenance.
- Published image: `ghcr.io/francisown/4b-llm-on-8gb-gpu/gateway:latest`
  (`sha-255690f`, digest `sha256:d6615e0c...`).
- Release tag: `2026.10.26`.
- Current verification: 101 passed / 7 skipped by default, 108 passed with
  C-Eval, coverage 80.17% with C-Eval (78.13% without), real-vLLM 2-hour soak 69,687 requests / 0 errors,
  p95 445.26 ms; HPA 2→4→6→2 and TLS smoke pass.
- Historical experiment data was removed from this clean branch.
