# Native Linux GPU node runbook

This is the next step after the WSL2 k3s experiment. The goal is a **stable**
single-node Kubernetes GPU deployment of the same model and gateway, with
real NVIDIA device scheduling, a model PVC, and measured TTFT/throughput.

Do not use WSL2 for this runbook. The WSL2 path was useful for proving that the
GPU can be scheduled, but its k3s/containerd lifecycle became unstable under
the real model workload (see [`K3S_GPU_EXPERIMENT.md`](K3S_GPU_EXPERIMENT.md)).

## Target environment

- Ubuntu 22.04 or 24.04, native Linux (not WSL2).
- One NVIDIA GPU with at least 8 GB VRAM (the current model was validated on an
  RTX 5060 8 GB).
- NVIDIA driver installed and `nvidia-smi` working.
- Root or sudo access.
- The model artifact available locally or on a network volume.

## 1. Install the NVIDIA container stack

```bash
nvidia-smi
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk --version
```

Verify that the toolkit can see the GPU:

```bash
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
nvidia-smi -L
```

## 2. Install k3s (single node)

```bash
curl -sfL https://get.k3s.io | sh -s - server \
  --disable traefik \
  --disable servicelb \
  --write-kubeconfig-mode 644
```

If port 6443 is already occupied on the host, choose another API port:

```bash
curl -sfL https://get.k3s.io | sh -s - server \
  --disable traefik --disable servicelb \
  --write-kubeconfig-mode 644 \
  --https-listen-port 6444
```

Check:

```bash
sudo k3s kubectl get nodes -o wide
```

## 3. Configure the NVIDIA runtime for k3s containerd

k3s v1.37 uses a containerd v3 config and imports drop-ins from
`/var/lib/rancher/k3s/agent/etc/containerd/config-v3.toml.d/`.

```bash
sudo nvidia-ctk runtime configure --runtime=containerd \
  --config=/etc/containerd/conf.d/99-nvidia.toml

sudo mkdir -p /var/lib/rancher/k3s/agent/etc/containerd/config-v3.toml.d
sudo cp /etc/containerd/conf.d/99-nvidia.toml \
  /var/lib/rancher/k3s/agent/etc/containerd/config-v3.toml.d/99-nvidia.toml

sudo systemctl restart k3s
```

Verify that the runtime is loaded:

```bash
sudo k3s crictl info | grep -A6 nvidia
```

Create the RuntimeClass:

```bash
cat <<'EOF' | sudo k3s kubectl apply -f -
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: nvidia
handler: nvidia
EOF
```

## 4. Install the NVIDIA device plugin

Use the official NVIDIA device-plugin DaemonSet. The WSL2 experiment manifests
were local-only and are not part of the validated deployment. The critical
parts are:

```yaml
spec:
  template:
    spec:
      runtimeClassName: nvidia
      containers:
        - name: nvidia-device-plugin-ctr
          image: nvcr.io/nvidia/k8s-device-plugin:v0.17.0
          env:
            - name: NVIDIA_VISIBLE_DEVICES
              value: all
            - name: NVIDIA_DRIVER_CAPABILITIES
              value: all
```

Verify:

```bash
kubectl get node -o jsonpath='{.status.allocatable.nvidia\.com/gpu}'
# expected: 1
```

Run a GPU smoke pod before deploying vLLM:

```bash
kubectl run gpu-smoke --image=nvcr.io/nvidia/k8s-device-plugin:v0.17.0 \
  --restart=Never --command -- nvidia-smi -L
kubectl logs gpu-smoke
```

Do not continue until the node advertises `nvidia.com/gpu` and the smoke pod
prints the GPU name.

## 5. Create the model PVC

For a single node, `local-path` is enough. For production, use a real
ReadWriteOnce block/network volume.

```bash
kubectl create namespace ai-inference
cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: vllm-model
  namespace: ai-inference
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: local-path
  resources:
    requests:
      storage: 10Gi
EOF
```

The PVC is `WaitForFirstConsumer`; create a temporary loader pod to bind it,
then copy the model into the PV path:

```bash
kubectl run model-loader -n ai-inference --image=busybox \
  --restart=Never --command -- sleep 3600 \
  --overrides='{"spec":{"volumes":[{"name":"m","persistentVolumeClaim":{"claimName":"vllm-model"}}],"containers":[{"name":"model-loader","image":"busybox","command":["sleep","3600"],"volumeMounts":[{"name":"m","mountPath":"/models"}]}]}}'
```

Get the PV path:

```bash
PV=$(kubectl get pvc vllm-model -n ai-inference -o jsonpath='{.spec.volumeName}')
kubectl get pv "$PV" -o jsonpath='{.spec.local.path}'
```

Copy the model from the host into that path, then delete the loader pod.
Verify `config.json` and `model.safetensors` are present.

## 6. Deploy vLLM with a GPU request

Keep the model server in the cluster and request the GPU explicitly:

```yaml
spec:
  runtimeClassName: nvidia
  containers:
    - name: vllm
      image: ai-inference-vllm:0.29.0-cu130
      args:
        - /models/qwen35
        - --served-model-name
        - Qwen3.5-4B-INT4-AWQ-self
        - --host
        - 0.0.0.0
        - --port
        - "8000"
        - --max-model-len
        - "2048"
        - --max-num-seqs
        - "8"
        - --gpu-memory-utilization
        - "0.78"
        - --enable-prefix-caching
        - --enable-chunked-prefill
      resources:
        limits:
          nvidia.com/gpu: "1"
      volumeMounts:
        - name: model
          mountPath: /models/qwen35
          readOnly: true
        - name: shm
          mountPath: /dev/shm
```

Use `startupProbe` with at least 15 minutes of tolerance. The first start may
compile kernels and capture CUDA graphs. For a first bring-up, `--enforce-eager`
reduces startup complexity; switch to compiled mode only after the stable path
is proven.

## 7. Deploy the gateway

Use the repository's gateway image and patch the upstream address:

```bash
kubectl -n ai-inference patch configmap inference-gateway-config \
  --type merge \
  -p '{"data":{"VLLM_BASE_URL":"http://vllm.ai-inference.svc.cluster.local:8000"}}'
kubectl -n ai-inference rollout restart deployment/inference-gateway
```

Verify:

```bash
kubectl -n ai-inference get pods
kubectl -n ai-inference port-forward svc/inference-gateway 9001:9000
curl -s http://127.0.0.1:9001/health
curl -s -X POST http://127.0.0.1:9001/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Reply with exactly: OK","max_tokens":16,"temperature":0}'
```

## 8. Measure with the same protocol

Run the in-cluster load generator:

```bash
kubectl create configmap loadgen-script \
  --from-file=benchmark/k8s_load_test.py -n ai-inference \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f k8s/benchmark/loadgen-job.yaml
kubectl wait --for=condition=complete job/gateway-loadgen \
  -n ai-inference --timeout=300s
kubectl logs job/gateway-loadgen -n ai-inference
```

Record model, runtime, GPU, driver, CUDA, input/output lengths, concurrency,
repetitions, and git revision. Report TTFT, TPOT, end-to-end p50/p95,
throughput, error rate, and VRAM.

## 9. TensorRT-LLM comparison

After vLLM is stable, build a TensorRT-LLM engine for the same checkpoint and
quantization, serve it behind an OpenAI-compatible endpoint, and run the same
protocol. Do not put the numbers in one table unless the model, quantization,
GPU, context length, concurrency, and client measurement point are identical.

## Stop conditions

Stop and investigate if:

- the node leaves `Ready` (`PLEG is not healthy`, `KubeletNotReady`);
- `nvidia.com/gpu` disappears from allocatable;
- vLLM is killed with `UnexpectedAdmissionError`;
- the device plugin is not Running;
- the pod cannot see the GPU (`Failed to infer device type`).

Those are cluster/runtime problems, not model bugs. Fix the node before tuning
the model.
