# WSL2 k3s GPU experiment: partial validation, not a success claim

Date: **2026-10-21**
Host: Windows + WSL2 Ubuntu 22.04, NVIDIA RTX 5060 8 GB, driver 595.97, CUDA 13.2.

This document records an attempt to answer a specific question:

> Can the local GPU be used by Kubernetes, or is GPU-in-Kubernetes
> impossible on this machine?

The answer is split:

- **Docker Desktop Kubernetes**: no. A pod requesting `nvidia.com/gpu: 1`
  stays Pending with `Insufficient nvidia.com/gpu`; the node has no NVIDIA
  device plugin or GPU resource advertisement.
- **WSL2 k3s**: **partially yes**. A real NVIDIA device plugin advertised
  `nvidia.com/gpu: 1`, and a GPU pod successfully ran `nvidia-smi -L`.
  Stable in-cluster vLLM serving, however, was **not** achieved.

## What worked

| Step | Result |
|---|---|
| Install k3s in WSL2 | k3s **v1.37.1+k3s1**, single node Ready |
| Configure containerd NVIDIA runtime | `nvidia` runtime loaded; RuntimeClass `nvidia` created |
| Deploy NVIDIA device plugin | `nvidia.com/gpu: 1` advertised by the node |
| GPU smoke pod | `gpu-smoke` scheduled with `nvidia.com/gpu: 1` and printed `GPU 0: NVIDIA GeForce RTX 5060` |
| Model PVC | `local-path` PVC `vllm-model` Bound, 10 GiB |
| Model copy | 3.6 GiB Qwen3.5-4B-INT4-AWQ model copied into the PV |
| vLLM image import | `ai-inference-vllm:0.29.0-cu130` imported into k3s containerd |
| In-cluster vLLM load | Model loaded (3.13 GiB), GPU usage reached **6.9 GiB**, warmup ran |

The GPU scheduling proof is real: the pod was scheduled, the NVIDIA runtime
injected `/dev/dxg` and the driver libraries, and `nvidia-smi` saw the GPU.

## What failed

After the image import and model load, the k3s node became unstable:

```text
Ready  False  KubeletNotReady
PLEG is not healthy: pleg has yet to be successful
```

Consequences:

1. Node transitions to `NotReady`.
2. Pods become `Completed` / `Unknown`.
3. The device plugin is terminated; `nvidia.com/gpu` drops from 1 to 0.
4. A new vLLM pod fails admission with:

```text
UnexpectedAdmissionError
Allocate failed due to no healthy devices present;
cannot allocate unhealthy devices nvidia.com/gpu
```

5. A workaround that removed the `nvidia.com/gpu` resource request but kept
   `runtimeClassName: nvidia` did **not** work: vLLM failed with
   `RuntimeError: Failed to infer device type`, because the GPU was not
   injected without the device-plugin allocation.

Restarting k3s/WSL can temporarily restore the node and the GPU resource, but
the PLEG failure recurs under the combined load of a 13.2 GB image import,
a 3.6 GB model, and vLLM initialization.

## Root cause

This is not a model or vLLM code failure. It is a **WSL2 + k3s + containerd +
NVIDIA runtime** lifecycle problem:

- WSL2 exposes the GPU as `/dev/dxg` plus WSL driver libraries, not as a normal
  Linux `/dev/nvidia*` device set.
- The k3s kubelet's PLEG cannot complete a successful sync with containerd
  under this workload, so the node leaves `Ready`.
- Once the node is NotReady, the device plugin is terminated and Kubernetes
  stops advertising the GPU. Every dependent pod is then killed or cannot be
  admitted.

Docker Desktop's own Kubernetes uses a managed kind node that does not expose
the WSL GPU at all, so it cannot be used as a fallback.

## Conclusion

- **GPU scheduling in Kubernetes: demonstrated once** on WSL2 k3s.
- **Stable in-cluster vLLM serving: not achieved.**
- **No in-cluster throughput or TTFT number is claimed.**
- The Docker-based vLLM + Kubernetes gateway path remains the validated
  serving architecture in this repository.

The next step is a native Linux GPU node. See
[`LINUX_GPU_RUNBOOK.md`](LINUX_GPU_RUNBOOK.md). The manifests used in this
experiment were local-only and are not presented as a validated deployment.

## Reproduce / inspect

The key commands were:

```bash
# k3s (WSL2)
k3s server --disable traefik --disable servicelb \
  --write-kubeconfig-mode 644 \
  --tls-san 127.0.0.1 --tls-san <wsl-ip> \
  --node-ip <wsl-ip> --flannel-iface eth0 \
  --https-listen-port 6444

# NVIDIA runtime drop-in for k3s containerd
nvidia-ctk runtime configure --runtime=containerd \
  --config=/etc/containerd/conf.d/99-nvidia.toml
cp /etc/containerd/conf.d/99-nvidia.toml \
  /var/lib/rancher/k3s/agent/etc/containerd/config-v3.toml.d/99-nvidia.toml

# Verify GPU scheduling
kubectl apply -f gpu-smoke.yaml
kubectl logs gpu-smoke
kubectl get node -o jsonpath='{.status.allocatable.nvidia\.com/gpu}'
```

Do not run this on a machine you need for other work without planning a cleanup;
the k3s cluster and containerd state can become unstable.
