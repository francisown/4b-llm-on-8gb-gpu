# Release

Status: **release candidate**.

## Artifact

- local image: `ai-inference-gateway:stable`
- registry image: `ghcr.io/francisown/4b-llm-on-8gb-gpu/gateway:latest`
- Dockerfile: `gateway/Dockerfile` (build from repository root)
- dependency lock: `gateway/requirements-image.lock.txt`

The local image was built and smoke-tested; the Kubernetes evidence records the
exact digest tested. The mutable `stable` tag may resolve to a newer local
rebuild.

## Release identity

| Field | Value |
|---|---|
| Package version | `1.0.0` (metadata only) |
| Source commit | see `git rev-parse HEAD` in this snapshot |
| Local image tag | `ai-inference-gateway:stable` |
| Registry channel | `ghcr.io/francisown/4b-llm-on-8gb-gpu/gateway:latest` |
| Model | Qwen3.5-4B-INT4-AWQ-self-v1, 3.568 GiB |
| Artifact manifest | `artifact-manifest.json`, emitted by the quantization CLI |
| GPU / runtime | RTX 5060 8 GB / vLLM 0.29.0 |
| Benchmark protocol | 16 prompts, 256/128, c=1 and c=4 (one run each); soak c=4 / 32 output |
| Restart | Compose or the K8s overlays in this repository |

The model weights and C-Eval archive are not included; see the third-party
assets section in the README.

## Verification

- 2-hour real-vLLM soak: 69,687 requests, 0 errors, p95 445.26 ms;
- 10-minute soak: 6,212 requests, 0 errors, p95 397.15 ms;
- C-Eval: 142/200, 99.5% agreement with INT4 v1, McNemar p 1.0000, κ 0.993;
- 32-case quant-quality: 25/32;
- Docker Desktop K8s: 2 replicas, HPA 2→4→6→2, TLS `/live` + `/health` 200;
- tests: 101 passed / 7 skipped by default; 108 passed with `CEVAL_ZIP`;
- coverage: 80.1% with C-Eval (78.13% without).

Evidence: [`soak`](../benchmark/results/soak-c4-7200s-telemetry.json),
[`C-Eval`](../benchmark/eval/int4-ceval-val-200.json),
[`paired stats`](../benchmark/eval/int4-vs-v1-agreement.json),
[`comparison`](../benchmark/eval/quantization-final-comparison.csv),
[`K8s`](../benchmark/results/k8s-smoke.json).

## Publish

The release workflow is `.github/workflows/release.yml`. Run it manually
(Actions → release → Run workflow) after pushing `main`. It builds from the
repository root and publishes:

```text
ghcr.io/francisown/4b-llm-on-8gb-gpu/gateway:latest
```

It also publishes a SHA tag for traceability.

## Known limits

- HPA/TLS use mock vLLM;
- real 4B GPU-in-K8s is not verified;
- direct vLLM benchmark is one run per concurrency; repeat before claiming
  variance or a regression;
- FP8 and INT4 v1 rows are frozen reference measurements, not reruns;
- image is not signed and the lock is version-pinned, not hash-pinned;
- model weights and C-Eval data are not redistributed;
- the gateway does not terminate TLS itself.
