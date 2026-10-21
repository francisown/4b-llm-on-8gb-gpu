# GPU-in-Kubernetes manifests (WSL2 k3s)

This overlay-like directory is the validated single-node GPU path:

- `vllm.yaml`: vLLM 0.29.0 deployment, `runtimeClassName: nvidia`, one GPU,
  hostPath model, explicit `VLLM_PORT=8000`;
- `gateway.yaml`: two gateway replicas, probes, NetworkPolicy, Service;
- `loadgen-job.yaml`: 100-request in-cluster load generator;
- `namespace.yaml`: audit/warn Pod Security. `enforce` is intentionally omitted
  because the WSL2 experiment mounts the model via `hostPath`; use a PVC on a
  real node pool.

## Apply

```bash
# The vLLM image and model must exist on the node.
kubectl apply -k k8s/gpu-inference

kubectl create configmap loadgen-script -n gpu-inference \
  --from-file=k8s_load_test.py=benchmark/k8s_load_test.py \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f k8s/gpu-inference/loadgen-job.yaml
kubectl wait --for=condition=complete job/gateway-loadgen -n gpu-inference --timeout=300s
kubectl logs job/gateway-loadgen -n gpu-inference
```

The recorded result is in
[`benchmark/results/k8s-gpu/`](../../benchmark/results/k8s-gpu/). It is a
100-request smoke test, not a performance-parity or production claim. The host
path measured 327.51 tok/s; this k3s path measured 147.17 tok/s with much worse
p95, and the cause is not yet isolated. After roughly six hours the WSL2 k3s
node became `NotReady` (flannel/PLEG), so long-run GPU serving is not claimed.

## Cleanup

```bash
kubectl delete namespace gpu-inference
```
