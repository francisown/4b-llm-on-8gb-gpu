# Benchmark protocol

This file is the single source of truth for what each headline number means.
If a number is not in this table, do not compare it with one that is.

## Protocol matrix

| Result | Model / runtime | Host | Input / output | Concurrency | Repeats | Evidence | Comparable? |
|---|---|---|---|---|---:|---|---|
| Quantization quality | BF16 / third-party FP8 / self FP8 v3 / INT4-AWQ; evaluation harness | RTX 5060 8 GB (BF16 layer-wise on CPU for quality only) | 200 C-Eval questions, max 8 output tokens, temperature 0 | 1 | 1 frozen set | `benchmark/eval/` | Only within this table |
| Quantization performance | vLLM 0.29.0, 256 input / 128 output | RTX 5060 8 GB, WSL2 | 256 / 128 | 1 and 4 | 3 runs per configuration | `benchmark/results/quant-*.json` | Only against the same 256/128 protocol |
| K8s Service load | vLLM 0.29.0 + gateway, prompt "Explain in one sentence why KV cache matters." | Docker Desktop K8s gateway + host vLLM | prompt above / 64 output tokens | 4 | 1 run | `benchmark/results/k8s/service-load-c4.json` | Only against the same 64-token Service protocol |
| Streaming TTFT | same as above, SSE | Docker Desktop K8s gateway, `port-forward` to one pod | prompt above / 64 output tokens | 4 | 1 run | `benchmark/results/k8s/stream-c4.json` | Single-pod; **not** Service-level |
| Gateway soak | mock OpenAI-compatible upstream | Docker Compose, CPU only | fixed mock response, 32 output tokens | 4 | 1 run, 120 s | `benchmark/results/observability/soak-c4-120s.json` | Gateway stability only; **not** vLLM performance |
| Backpressure | mock upstream | Docker Compose, CPU only | fixed mock response, 8 output tokens | 16 | 1 run, 30 s | `benchmark/results/observability/backpressure-c16-30s.json` | 429 behavior only |
| Custom CUDA engine | `qwen3.5-fp8-cuda`, single stream | RTX 5060 8 GB | separate repo protocol | 1 | separate repo | [`qwen3.5-fp8-cuda`](https://github.com/francisown/qwen3.5-fp8-cuda) | **No** — different engine and protocol |
| TensorRT-LLM | not measured | — | — | — | — | [`RUNTIME_COMPARISON.md`](RUNTIME_COMPARISON.md) | No result claimed |

## Rules

1. **Do not compare across rows** unless model, quantization, runtime, GPU,
   input length, output length, and concurrency all match.
2. Rows marked as a single run are indicative. Re-run at least three times
   before quoting them as a stable result.
3. The K8s Service row and the 256/128 quantization row are different
   protocols. Do not put them in one "throughput" column.
4. The mock upstream exists only to validate the gateway, dashboard, and
   admission control. It is not a model and cannot support quality claims.
5. The custom CUDA row is a different engine in a different repository. The
   54 tok/s number is not a competitor row for batched vLLM.
6. TensorRT-LLM has no measured row. The harness and protocol are documented,
   but no number is invented.

## What to record for a new run

- Git revision and image digest.
- Model and quantization.
- Runtime and version.
- GPU, driver, CUDA.
- Host OS / container runtime.
- Input and output token counts, temperature, thinking mode.
- Concurrency, request count, repetitions, warmup.
- TTFT, TPOT, end-to-end p50/p95, throughput, error rate, VRAM.
- Raw JSON path.

## Regenerate

```bash
python scripts/verify_local.py
python benchmark/soak_test.py --url http://127.0.0.1:9000/chat \
  --duration 120 --concurrency 4 \
  --output benchmark/results/observability/soak-c4-120s.json
```

The K8s load generator is `benchmark/k8s_load_test.py`; the in-cluster Job is
`k8s/benchmark/loadgen-job.yaml`.
