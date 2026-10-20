#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE="${NAMESPACE:-ai-inference}"
JOB="${JOB:-gateway-loadgen}"

kubectl create configmap loadgen-script \
  --from-file="$ROOT/benchmark/k8s_load_test.py" \
  -n "$NAMESPACE" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl delete job "$JOB" -n "$NAMESPACE" --ignore-not-found
kubectl apply -f "$ROOT/k8s/benchmark/loadgen-job.yaml"

if ! kubectl wait --for=condition=complete "job/$JOB" -n "$NAMESPACE" --timeout=300s; then
  kubectl logs "job/$JOB" -n "$NAMESPACE" || true
  exit 1
fi
kubectl logs "job/$JOB" -n "$NAMESPACE"
