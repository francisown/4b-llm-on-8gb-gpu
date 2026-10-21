# Contributing

This repository is a small inference-delivery project. Keep changes focused,
leave a verification command or artifact, and do not commit model weights,
datasets, secrets, caches, or machine-local benchmark logs.

## Local checks

```bash
python -m pip install -r gateway/requirements-dev.txt pyyaml
python scripts/verify_local.py
python scripts/validate_manifests.py
python scripts/validate_workflows.py
```

`verify_local.py` runs the cost tests, the gateway tests (no GPU/model), and a
Python syntax check. The manifest and workflow validators are deterministic and
do not need a cluster.

## Gateway changes

```bash
cd gateway
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The tests use a fake vLLM upstream. Add a test for every new failure path,
authentication rule, or observability contract. Keep `/live`, `/health`, and
`/metrics` reachable without an API key.

## Observability demo

```bash
docker compose -f deploy/observability/compose.yaml up -d --build
# Grafana:    http://localhost:3000 (admin/admin)
# Prometheus: http://localhost:9090
# Gateway:    http://localhost:9000
docker compose -f deploy/observability/compose.yaml down
```

The demo uses a mock OpenAI-compatible upstream. It validates metrics,
dashboards, admission control, and auth; it is not a model benchmark.

## Soak and load tests

```bash
python benchmark/soak_test.py \
  --url http://127.0.0.1:9000/chat \
  --duration 120 --concurrency 4 \
  --output benchmark/results/observability/soak-c4-120s.json
```

Use a separate output file for each scenario. Do not overwrite an existing
evidence file without recording why.

## Pull request checklist

- [ ] `python scripts/verify_local.py` passes.
- [ ] `python scripts/validate_manifests.py` passes.
- [ ] `python scripts/validate_workflows.py` passes.
- [ ] `git diff --check` is clean.
- [ ] New behavior has a focused test or a reproducible command.
- [ ] No secrets, model weights, datasets, `.env` files, or caches are staged.
- [ ] README/docs describe any new claim and its limits.

## Release

A release is created by pushing a tag such as `v0.2.1`. The `release` workflow
runs the tests and publishes the gateway image to GHCR. Update
`GATEWAY_VERSION` and the image tag in `k8s/` in the same change. See
[`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md).
