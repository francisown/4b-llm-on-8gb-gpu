# Release

Status: **release candidate**.

## Artifact

- local image: `ai-inference-gateway:stable`
- registry image: `ghcr.io/francisown/4b-llm-on-8gb-gpu/gateway:latest`
- Dockerfile: `gateway/Dockerfile` (build from repository root)
- dependency lock: `gateway/requirements-image.lock.txt`

The local image was built and smoke-tested; the Kubernetes evidence was
recorded with the same tag.

## Verification

- 2-hour real-vLLM soak: 69,687 requests, 0 errors, p95 445.26 ms;
- 10-minute soak: 6,212 requests, 0 errors, p95 397.15 ms;
- C-Eval: 142/200, 99.5% per-question agreement with the earlier INT4 report;
- 32-case quant-quality: 25/32;
- Docker Desktop K8s: 2 replicas, HPA 2→4→6→2, TLS `/live` + `/health` 200;
- tests: 100 passed / 7 skipped by default; 107 passed with `CEVAL_ZIP`;
- coverage: 80.03% with C-Eval (78.03% without).

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
- image is not signed and the lock is version-pinned, not hash-pinned;
- the gateway does not terminate TLS itself.
