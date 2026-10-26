# Benchmark

Current evidence lives in `results/`; the clean branch keeps only the latest
current runs.

## Runners

- `soak_test.py` — closed-loop gateway soak with optional telemetry:
  `active`, `waiting`, `gpu_memory_mb`, `gpu_utilization_pct`;
- `k8s_load_test.py` — fixed-request load for an in-cluster service.

## Current results

| File | What |
|---|---|
| `results/soak-c4-7200s-telemetry.json` | 2-hour real-vLLM gateway soak |
| `results/soak-c4-600s-metrics-final.json` | 10-minute real-vLLM gateway soak |
| `results/int4-c1.json` | direct vLLM, c=1 |
| `results/int4-c4.json` | direct vLLM, c=4 |
| `results/k8s-smoke.json` | final-image Kubernetes smoke |
| `results/k8s-hpa-tls.json` | HPA and TLS demo |

`results/INDEX.md` is the claim-to-evidence index.

## Rules

- Do not merge different protocols.
- Do not treat mock-upstream runs as model performance.
- Do not treat 16-prompt microbenchmarks as capacity plans.
- The direct vLLM files are one run per concurrency; repeat before claiming
  variance or a regression.
- Raw vLLM JSON keeps the original host model paths; use
  `benchmark/eval/int4-artifact-manifest.json` for model identity.
- Keep the raw file and the protocol summary together.
