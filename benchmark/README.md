# Benchmark and evaluation data

This directory contains both quality data and performance artifacts. Read
[`../docs/BENCHMARK_PROTOCOL.md`](../docs/BENCHMARK_PROTOCOL.md) before quoting
any number.

## Layout

| Path | Contents | Status |
|---|---|---|
| `eval/` | Frozen 200-question C-Eval set, per-question results for four models, combined comparison table | Authoritative |
| `results/` | Raw vLLM performance JSON (concurrency sweeps, long context, speculative decoding, repeat comparisons) | Authoritative for the stated protocol |
| `results/k8s/` | K8s gateway load, pod kill, rollback, Prometheus queries, GPU probe | Authoritative for the gateway evidence |
| `results/observability/` | Grafana/Prometheus smoke, auth smoke, soak, backpressure | Authoritative for the gateway/observability evidence |
| `results/speculative/` | Speculative-decoding logs and metrics | Historical experiment archive |
| `results/rebaseline/`, `results/runner-verify/` | Runner/rebaseline logs | Historical investigation archive |

## Scripts

```bash
# Gateway load through a running gateway (streaming or non-streaming)
python benchmark/k8s_load_test.py --url http://127.0.0.1:9000/chat \
  --requests 100 --concurrency 4 --output /tmp/load.json

# Gateway soak / backpressure
python benchmark/soak_test.py --url http://127.0.0.1:9000/chat \
  --duration 120 --concurrency 4 --output /tmp/soak.json
```

The mock stack used by the observability evidence is in
`deploy/observability/`; it is a gateway test, not a model benchmark.

## Rules

- Keep raw JSON; do not overwrite an evidence file with a new run silently.
- Name files with protocol and concurrency, e.g. `service-load-c4.json`.
- A single run is indicative. Mark it as such in reports.
- Do not compare the 256/128 quantization rows with the 64-token K8s rows.
- Do not put the custom-CUDA 54 tok/s number next to batched vLLM.

## Historical metadata gap

Many files under `results/` were recorded before the metadata checklist in
`docs/BENCHMARK_PROTOCOL.md` existed. They are retained as measured, but some do
not contain a git revision, GPU driver, or CUDA version. They are not
retroactively edited; new runs must include those fields.
