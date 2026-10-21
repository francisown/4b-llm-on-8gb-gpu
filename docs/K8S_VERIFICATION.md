# Kubernetes verification: gateway layer, not GPU scheduling

Verification date: **2026-10-21**
Repository revision: working tree based on `566eb18` plus the changes in this commit.

> **Version note:** the measured run used **v0.2.0**. **v0.2.1** adds optional
> API-key authentication and a versioned image tag; the serving path and the
> numbers below are unchanged.

This document records what was actually run. It deliberately separates the
**gateway layer** (which Kubernetes did manage) from the **GPU inference layer**
(which stayed outside the cluster on this single-GPU Windows/WSL2 host).

## What was deployed

| Component | Version / image | Where it ran |
|---|---|---|
| Kubernetes | Docker Desktop 4.91.0, Kubernetes **v1.36.1** | single-node `desktop-control-plane` |
| Gateway | `ai-inference-gateway:v0.2.0`, FastAPI + Uvicorn | 2 pods in namespace `ai-inference` |
| Model server | vLLM **0.29.0**, Qwen3.5-4B-INT4-AWQ-self | host Docker container with `--gpus all` |
| Metrics | Prometheus **v2.55.1** | 1 pod, Kubernetes pod discovery |
| GPU | NVIDIA RTX 5060, 8,151 MiB, driver 595.97, CUDA 13.2 | host/WSL2 |

The deployment in `k8s/` sets:

- 2 replicas, `maxUnavailable: 0`, `maxSurge: 1`;
- startup `/live`, readiness `/health` (checks the vLLM dependency), liveness `/live`;
- `terminationGracePeriodSeconds: 30`, `preStop` sleep 5 s, Uvicorn graceful shutdown 20 s;
- CPU/memory requests and limits, non-root user, read-only root filesystem, `/tmp` emptyDir;
- PodDisruptionBudget `minAvailable: 1`;
- HPA manifest (2–4 replicas, CPU 70%) — present but **not active** on this cluster;
- Prometheus scraping by pod, so both replicas are visible separately.

## Apply and rollout

```powershell
kubectl apply -k .\k8s
kubectl rollout status deployment/inference-gateway -n ai-inference --timeout=180s
kubectl apply -k .\k8s\observability
kubectl rollout status deployment/prometheus -n ai-inference --timeout=240s
```

Observed: the deployment rolled from the previous image to `v0.2.0` with
`maxUnavailable: 0`; the old pod stayed `Running` until the new pod was Ready.

## Measured results

All requests used the same gateway contract, `temperature=0`,
`enable_thinking=false`, and the fixed Qwen3.5-4B-INT4-AWQ model above.
Raw JSON is in [`benchmark/results/k8s/`](../benchmark/results/k8s/).

### 1. Service-level load (in-cluster client, 2 gateway replicas)

| Metric | Result |
|---|---:|
| Requests / concurrency | 100 / 4 |
| Duration | 12.556 s |
| Throughput | **7.964 req/s** |
| Output token throughput | **326.53 tok/s** |
| Latency mean / p50 / p95 / p99 | 501.85 / 500.30 / 513.81 / 523.28 ms |
| Errors | **0 / 100** |
| Pod distribution | 25 requests / 75 requests |

The client ran as a Kubernetes Job and called
`http://inference-gateway.ai-inference.svc.cluster.local:9000/chat`.
The two-replica split proves the Service was routing to both pods; the skew is
expected from HTTP keep-alive connection reuse, not a broken Service.

### 2. Streaming TTFT through a port-forward

| Metric | Result |
|---|---:|
| Requests / concurrency | 20 / 4 |
| Duration | 2.620 s |
| Throughput | 7.633 req/s |
| Output token throughput | 312.94 tok/s |
| TTFT mean / p50 / p95 / p99 | 103.5 / **96.1** / 138.6 / 141.8 ms |
| End-to-end latency p50 / p95 | 514.0 / 565.62 ms |
| Errors | 0 / 20 |

`kubectl port-forward service/...` selects one backend pod, so this is a
single-pod streaming measurement, not a Service load-balance test.

### 3. Pod kill during live load

A 300-request Job was started, then one gateway pod was deleted while the Job
was running. The remaining replica kept serving.

| Metric | Result |
|---|---:|
| Requests / concurrency | 300 / 4 |
| Duration | 30.432 s |
| Throughput | 9.858 req/s |
| Output token throughput | 315.457 tok/s |
| Latency mean / p50 / p95 / p99 | 405.44 / 403.16 / 425.71 / 428.30 ms |
| Errors | **0 / 300** |
| Pod distribution | victim 54 / survivor 246 |

This is the strongest reliability result in the run: killing one gateway pod
during active traffic did not produce a single failed request. The mechanism is
the combination of two replicas, a Service with ready endpoints, `preStop`
draining, and Uvicorn graceful shutdown.

### 4. Recovery time after a direct pod deletion

- Victim: `inference-gateway-686fbcc5bb-d7qkr`
- Replacement Ready after **7.6 s**
- Service endpoints updated automatically to the two new pod IPs.

## Rollout and rollback

A deliberately broken image tag was applied:

```powershell
kubectl set image deployment/inference-gateway gateway=ai-inference-gateway:v2 -n ai-inference
```

Observed:

- the new pod stayed `ImagePullBackOff`;
- both old `v0.2.0` pods remained `1/1 Running`;
- `kubectl rollout status --timeout=20s` failed, as expected;
- `kubectl rollout undo deployment/inference-gateway -n ai-inference` returned
  to `v0.2.0` and completed a successful rollout.

This is the intended `maxUnavailable: 0` behavior: a bad release cannot take
down the serving replicas.

## Observability

Prometheus discovers gateway pods directly (not through the Service), so both
replicas report independently:

```text
targets: inference-gateway-...-d7qkr  up
         inference-gateway-...-nclbc  up
inference_gateway_upstream_healthy{pod=...-d7qkr} 1
inference_gateway_upstream_healthy{pod=...-nclbc} 1
inference_gateway_info{version="0.2.0",pod=...} 1
```

Raw query results:

- [`prometheus-targets.json`](../benchmark/results/k8s/prometheus-targets.json)
- [`prometheus-inference_gateway_upstream_healthy.json`](../benchmark/results/k8s/prometheus-inference_gateway_upstream_healthy.json)
- [`prometheus-inference_gateway_requests_total.json`](../benchmark/results/k8s/prometheus-inference_gateway_requests_total.json)

### A real health-check bug found by the cluster

The first version of the `/health` client reused keep-alive connections. vLLM
closed idle connections, so the gateway intermittently logged
`health_check_failed` with `RemoteProtocolError`, and one pod's
`inference_gateway_upstream_healthy` gauge dropped to 0 even though the pod was
still Ready. The fix is in `gateway/gateway.py`:

- health client: `max_keepalive_connections=0`;
- health request: `Connection: close`.

After the fix and a new rollout, both pods reported `upstream_healthy=1` and no
new `health_check_failed` events appeared. A regression test asserts that the
health request sends `Connection: close`.

## What Kubernetes did **not** do on this host

The GPU inference workload was **not** scheduled by Kubernetes. A pod requesting
`nvidia.com/gpu: 1` stayed Pending:

```text
Warning  FailedScheduling  0/1 nodes are available:
1 Insufficient nvidia.com/gpu.
```

Raw output: [`gpu-probe.txt`](../benchmark/results/k8s/gpu-probe.txt).

Docker Desktop's Kubernetes node has no NVIDIA device plugin or GPU resource
advertisement. vLLM therefore ran as a host Docker container with `--gpus all`,
and the gateway pods reached it through `host.docker.internal:8000`.
This is a **validated gateway deployment**, not a validated GPU-scheduling
deployment. Moving vLLM into the cluster requires:

1. a Linux GPU node with the NVIDIA driver and container toolkit;
2. the NVIDIA device plugin (or GPU operator) advertising `nvidia.com/gpu`;
3. a model artifact mounted from a PVC or a pre-baked image;
4. a GPU-aware runtime class and resource requests;
5. a readiness probe that tolerates the model's cold-start time.

The repository does not claim those steps were completed.

## HPA status

`kubectl get hpa` reports:

```text
cpu: <unknown>/70%
ScalingActive  False  FailedGetResourceMetric
```

The Docker Desktop cluster has no metrics-server, so the HPA manifest is
present but **not validated**. Do not describe autoscaling as working until a
metrics pipeline is installed and a scale-out event is observed.

## Reproduce

```bash
# 1. Build and import the gateway image into the Docker Desktop node
docker build -t ai-inference-gateway:v0.2.0 ./gateway
docker save ai-inference-gateway:v0.2.0 | \
  docker exec -i desktop-control-plane ctr -n k8s.io images import -

# 2. Start vLLM on the host with GPU access (see README for the model path)
#    The gateway ConfigMap points at host.docker.internal:8000.

# 3. Deploy
kubectl apply -k ./k8s
kubectl apply -k ./k8s/observability
kubectl rollout status deployment/inference-gateway -n ai-inference

# 4. Run the in-cluster load test
kubectl create configmap loadgen-script \
  --from-file=benchmark/k8s_load_test.py -n ai-inference \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl delete job gateway-loadgen -n ai-inference --ignore-not-found
kubectl apply -f k8s/benchmark/loadgen-job.yaml
kubectl wait --for=condition=complete job/gateway-loadgen -n ai-inference --timeout=300s
kubectl logs job/gateway-loadgen -n ai-inference
```

## Limits of this verification

- Single node, single GPU, one vLLM instance; the model server itself is still a
  single point of failure.
- No TLS, authentication, per-tenant quota, or network policy.
- No long-duration soak test, no memory-leak profile, no p99 under sustained load.
- HPA not validated (no metrics-server).
- GPU scheduling not validated (no device plugin).
- TensorRT-LLM was not measured; see
  [`RUNTIME_COMPARISON.md`](RUNTIME_COMPARISON.md).
