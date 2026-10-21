# Release checklist

Use this checklist for a gateway image or manifest release. The goal is a
reproducible artifact and a rollback path that was tested before traffic moves.

## Pre-release

- [ ] `python scripts/verify_local.py` passes (5 cost tests + 15 gateway tests).
- [ ] `python scripts/validate_manifests.py` passes.
- [ ] `python scripts/validate_workflows.py` passes.
- [ ] `kubectl kustomize k8s` and `kubectl kustomize k8s/observability` render.
- [ ] `docker build -t ai-inference-gateway:<version> gateway/` succeeds.
- [ ] The mock observability stack starts:
      `docker compose -f deploy/observability/compose.yaml up -d --build`.
- [ ] `/live`, `/health`, `/chat`, and `/chat/stream` work through the gateway.
- [ ] Prometheus scrapes the gateway; Grafana shows the dashboard.
- [ ] The reference load test produces zero errors and records raw JSON.
- [ ] No secrets, model weights, or machine-local paths are in the image or repo.

## Versioning

- Gateway image: `ai-inference-gateway:v<major>.<minor>.<patch>`.
- Chart/manifest: same version in `k8s/configmap.yaml` (`GATEWAY_VERSION`) and
  the image tag.
- Record the image digest, not only the tag.
- Model artifact: record the immutable path and SHA-256.

## Release

- [ ] Push the image to the registry.
- [ ] Update the Deployment image tag and `GATEWAY_VERSION`.
- [ ] Apply with `kubectl apply -k k8s` (or the environment overlay).
- [ ] `kubectl rollout status deployment/inference-gateway -n ai-inference`.
- [ ] Verify two Ready replicas and Service endpoints.
- [ ] If auth is enabled, confirm the `inference-gateway-secret` exists and the key was rotated.
- [ ] Run a canary request set and compare error rate/TTFT with the previous revision.
- [ ] Confirm `inference_gateway_upstream_healthy` is 1 on every replica.
- [ ] Confirm the Prometheus targets are up.

## Rollback

- [ ] `kubectl rollout undo deployment/inference-gateway -n ai-inference`.
- [ ] Verify the old ReplicaSet is Ready and the bad revision is gone.
- [ ] Run the same canary request set.
- [ ] Record the incident, the failed image digest, and the rollback revision.

The repository has a tested rollback path: a deliberately broken image stayed
in `ImagePullBackOff`, both old replicas kept serving, and `rollout undo`
recovered. See `benchmark/results/k8s/rollback.txt`.

## Artifacts to publish

- Gateway image digest.
- Model artifact path and SHA-256.
- `benchmark/results/k8s/*.json` (load, pod kill, Prometheus queries).
- Release notes with the benchmark conditions and known limitations.
- The current `docs/PERFORMANCE_REPORT.md` and `docs/SLO.md`.

## Post-release

- [ ] Watch error rate, TTFT p95, queue depth, and `upstream_healthy` for 24 hours.
- [ ] Compare the error budget burn with the SLO in `docs/SLO.md`.
- [ ] If the budget burn is abnormal, roll back and investigate.
- [ ] Remove temporary load-test Jobs and unused images.

## Do not ship if

- the node is NotReady or `nvidia.com/gpu` is not advertised (GPU path);
- the gateway has no readiness probe or the readiness probe does not check the upstream;
- the rollback path was not exercised;
- a benchmark number lacks model, runtime, GPU, input/output length, concurrency, and revision metadata.
