# Verification

Current implementation: capability-module serving tree. All numbers below were
produced on the current tree/evidence set; historical experiments were
removed from this clean branch.

## Deterministic checks

```bash
python -m pip install -e ".[web,dev]" pyyaml
python scripts/verify_local.py
python scripts/validate_manifests.py   # 48 Kubernetes documents
python scripts/validate_workflows.py
python scripts/validate_docs.py
```

- tests: **101 passed / 7 skipped** without the C-Eval archive;
- with `CEVAL_ZIP` set: **108 passed**;
- coverage: **78.13%** without the C-Eval archive; **80.1%** with `CEVAL_ZIP`; CI floor 77%;
- ruff: pass;
- mypy: `gateway/gateway.py src/llm8g`, 40 source files;
- Kubernetes manifests: 48 documents;
- workflows: 2 files;
- docs: local links and manifest count.

## Real vLLM, 4B INT4, 2-hour soak

- Host: Windows + WSL2 Ubuntu 22.04, RTX 5060 8 GB, driver 595.97;
- Runtime: vLLM 0.29.0;
- Model: Qwen3.5-4B-INT4-AWQ-self-v1;
- Gateway: `ai-inference-gateway:stable`;
- Protocol: c=4, 32 output tokens, 7,200 s.

Result:

- **69,687 requests**, **0 errors**, 9.68 rps;
- p50 413.17 ms, p95 445.26 ms, p99 458.04 ms;
- max active 4, max waiting 1;
- GPU memory 6,993–7,326 MB, GPU utilization 58–98%;
- after drain: active 0, waiting 0;
- `/health` before/after: vLLM ok.

Evidence: [`benchmark/results/soak-c4-7200s-telemetry.json`](../benchmark/results/soak-c4-7200s-telemetry.json).

## 10-minute gateway soak

- **6,212 requests**, **0 errors**, 10.35 rps;
- p50 384.4 ms, p95 397.15 ms, p99 418.05 ms;
- active/waiting return to 0.

Evidence: [`benchmark/results/soak-c4-600s-metrics-final.json`](../benchmark/results/soak-c4-600s-metrics-final.json).

## Direct vLLM benchmark

16 prompts, 256 input / 128 output, temperature 0, compiled vLLM:

| Concurrency | Output throughput | TTFT p50 | TPOT p50 |
|---:|---:|---:|---:|
| 1 | 95.55 tok/s | 77.03 ms | 9.94 ms |
| 4 | 309.55 tok/s | 271.66 ms | 10.88 ms |

The current files are one run per concurrency; repeat before claiming variance
or a regression.

Evidence: [`int4-c1`](../benchmark/results/int4-c1.json), [`int4-c4`](../benchmark/results/int4-c4.json).

## Quality

- C-Eval 200 questions: **142/200 (71.0%)**, Wilson 95% **64.4–76.8%**;
- vs the earlier INT4 v1 report: **99.5% agreement** (95% Wilson
  **97.2–99.9%**), 1 fixed / 0 broken, McNemar p **1.0000**, κ **0.993**;
- 32-case quant-quality smoke: **25/32 (78.1%)**, strict = relaxed.

Evidence: [`C-Eval`](../benchmark/eval/int4-ceval-val-200.json),
[`INT4 v1`](../benchmark/eval/self-int4-awq-v1-ceval-val-200.json),
[`paired stats`](../benchmark/eval/int4-vs-v1-agreement.json),
[`quant quality`](../benchmark/eval/int4-quant-quality.json).

## Docker

```bash
docker build -f gateway/Dockerfile -t ai-inference-gateway:stable .
```

- image built from the repository root;
- dependency lock: `gateway/requirements-image.lock.txt`;
- container smoke: `/live`, `/health`, `/chat`, `/chat/stream`, `/metrics`;
- optional API key: no key → 401, correct key → 200;
- registry image: `ghcr.io/francisown/4b-llm-on-8gb-gpu/gateway:latest`;
- published manifest digest: `sha256:d6615e0c4c3216af0e767eb9028f25dd6804a26a74ea0d57bd5301a199d69ca2`.

## Kubernetes

Docker Desktop Kubernetes `v1.36.1`, final image:

- 2 gateway replicas Ready;
- full `gateway/smoke_test.py` pass;
- rolling restart and dual-pod kill recover to 2/2;
- HPA queue-depth: 2 → 4 at ~20 s → 6 at ~50 s, then 6 → 5 → 4 → 3 → 2;
- TLS demo: HTTPS `/live` and `/health` both 200;
- HPA/TLS use in-cluster mock vLLM, not the 4B model.

Evidence: [`k8s smoke`](../benchmark/results/k8s-smoke.json), [`HPA/TLS`](../benchmark/results/k8s-hpa-tls.json).

## Not verified in this clean branch

- real 4B vLLM inside Kubernetes (HPA/TLS use mock);
- offline bundle (not included in this branch);
- TensorRT-LLM comparison.
