# Kubernetes 部署：网关层已实测，GPU 调度未验证

这份 README 记录 **2026-10-21** 在本机 Docker Desktop Kubernetes 上真实跑过的结果，
不是“清单写好了”的同义词。

## 结论先行

| 项目 | 结果 |
|---|---|
| 集群 | Docker Desktop 4.91.0，Kubernetes v1.36.1，单节点 `desktop-control-plane` |
| 网关 | `ai-inference-gateway:v0.2.3`，2 副本，全部 Ready |
| 模型服务 | vLLM 0.29.0 + Qwen3.5-4B-INT4-AWQ，**在集群外**的宿主 Docker 中运行 |
| 集群内 Service 压测 | 100 请求 / 并发 4，**0 错误，326.53 tok/s**，两个 Pod 分别收到 25 / 75 请求 |
| 压测中强杀 1 个 Pod | 300 请求 / 并发 4，**0 错误，315.46 tok/s** |
| Pod 强杀恢复 | 替换 Pod **7.6 秒**后 Ready，Service endpoints 自动更新 |
| 坏版本回滚 | 新 Pod `ImagePullBackOff`，两个旧副本继续服务；`rollout undo` 后恢复 |
| Prometheus | 两个网关 Pod 均 `up`，`upstream_healthy=1`，按 Pod 抓取 |
| HPA | 清单存在，但集群无 metrics-server，`cpu: <unknown>/70%`，**未生效** |
| K8s 调度 GPU | `nvidia.com/gpu: 1` 探针一直 Pending：`Insufficient nvidia.com/gpu`，**未验证** |

完整原始结果与限制见 [`../docs/K8S_VERIFICATION.md`](../docs/K8S_VERIFICATION.md)。

## 为什么模型不放进集群

本机是 Windows/WSL2 + 单张 RTX 5060。Docker Desktop 的 Kubernetes 节点没有
NVIDIA device plugin，也不会广告 `nvidia.com/gpu` 资源；把 vLLM 放进去只会
Pending。因此当前拓扑是：

```text
浏览器 / 压测 Job
        │
        ▼
Service/inference-gateway (ClusterIP:9000)
        │
        ▼
Deployment/inference-gateway (2 Pods)
        │  http://host.docker.internal:8000
        ▼
宿主 Docker: vLLM 0.29.0 + Qwen3.5-4B-INT4-AWQ + RTX 5060
```

Kubernetes 管理的是**无状态网关层**：副本、Service 发现、探针、滚动更新、
PDB、指标抓取。它不是 GPU 调度层。

## 前置条件

1. Docker Desktop 已启动，Kubernetes 已启用。
2. `kubectl config current-context` 为 `docker-desktop`，`kubectl get nodes` 为 Ready。
3. 宿主已启动 vLLM，端口 8000 可访问。
4. 已构建网关镜像。

## 构建并导入镜像

Docker Desktop 的 Kubernetes 节点使用自己的 containerd，宿主 Docker 里的镜像
不会自动出现。用 `cmd` 管道导入，避免 PowerShell 破坏 tar 二进制：

```powershell
docker build -t ai-inference-gateway:v0.2.3 .\gateway
cmd /c "docker save ai-inference-gateway:v0.2.3 | docker exec -i desktop-control-plane ctr -n k8s.io images import -"
docker exec desktop-control-plane ctr -n k8s.io images list | Select-String ai-inference-gateway
```

Deployment 使用 `imagePullPolicy: IfNotPresent`。本地节点已有镜像时不会联网；
如果镜像不存在，Pod 会进入 `ErrImagePull`，这时应检查导入命令，而不是盲目改
成 `Always`。

对于有镜像仓库的集群，可以直接使用 GHCR 镜像：

```yaml
image: ghcr.io/francisown/8gb-llm-inference-delivery/gateway:v0.2.3
imagePullPolicy: IfNotPresent
```

本地 Docker Desktop/kind 仍可用 `docker save` 导入；详见
[`../docs/RELEASE.md`](../docs/RELEASE.md)。

## 部署

```powershell
kubectl apply -k .\k8s
kubectl rollout status deployment/inference-gateway -n ai-inference --timeout=180s
kubectl get pods,deploy,svc,pdb -n ai-inference -o wide
```

清单包含：

- 2 副本，`maxUnavailable: 0`、`maxSurge: 1`；
- startup `/live`、readiness `/health`、liveness `/live`；
- `terminationGracePeriodSeconds: 30` + `preStop sleep 5`；
- 非 root、只读根文件系统、`/tmp` emptyDir；
- CPU/内存 requests 与 limits；
- PDB `minAvailable: 1`；
- HPA 清单（需要 metrics-server 才生效）；
- Prometheus 抓取注解与按 Pod 抓取配置。

## 验证

```powershell
kubectl port-forward service/inference-gateway 9001:9000 -n ai-inference
```

另开一个窗口：

```powershell
curl.exe --noproxy "*" http://127.0.0.1:9001/live
curl.exe --noproxy "*" http://127.0.0.1:9001/health
```

`/live` 只表示进程活着；`/health` 还会检查 vLLM 上游。响应头会带
`X-Gateway-Pod` 和 `X-Gateway-Version`。

## 集群内压测

压测客户端必须从集群内部访问 Service，`port-forward` 只会选中一个 Pod，不能
用来验证 Service 分流。

```powershell
kubectl create configmap loadgen-script `
  --from-file=benchmark/k8s_load_test.py -n ai-inference `
  --dry-run=client -o yaml | kubectl apply -f -

kubectl delete job gateway-loadgen -n ai-inference --ignore-not-found
kubectl apply -f k8s/benchmark/loadgen-job.yaml
kubectl wait --for=condition=complete job/gateway-loadgen -n ai-inference --timeout=300s
kubectl logs job/gateway-loadgen -n ai-inference
```

本机实测输出（`benchmark/results/k8s/service-load-c4.json`）：

```text
100 requests, concurrency 4, 12.556 s
0 errors, 7.964 req/s, 326.53 tok/s
p50 500.30 ms, p95 513.81 ms
pods: 25 / 75
```

## 故障与回滚

删除一个 Pod，观察 Deployment 补回：

```powershell
kubectl delete pod -n ai-inference -l app.kubernetes.io/name=inference-gateway
kubectl get pods -n ai-inference -w
```

坏版本回滚：

```powershell
kubectl set image deployment/inference-gateway gateway=ai-inference-gateway:v2 -n ai-inference
kubectl rollout status deployment/inference-gateway -n ai-inference --timeout=20s
kubectl rollout undo deployment/inference-gateway -n ai-inference
kubectl rollout status deployment/inference-gateway -n ai-inference --timeout=120s
```

实测：坏镜像 Pod 停在 `ImagePullBackOff`，两个旧副本保持 Ready；undo 后恢复。

## Prometheus

```powershell
kubectl apply -k .\k8s\observability
kubectl rollout status deployment/prometheus -n ai-inference --timeout=240s
kubectl port-forward svc/prometheus 9090:9090 -n ai-inference
```

Prometheus 使用 Kubernetes pod discovery，直接抓每个网关 Pod，而不是抓
Service。这样 `inference_gateway_upstream_healthy`、请求数、TTFT 直方图都能
按 Pod 区分。原始查询结果在 [`../benchmark/results/k8s/`](../benchmark/results/k8s/)。

## 可选 API Key 认证

`GATEWAY_API_KEY` 为空时认证关闭。要开启：

```powershell
kubectl create secret generic inference-gateway-secret `
  -n ai-inference `
  --from-literal=GATEWAY_API_KEY=replace-with-a-long-random-token
kubectl rollout restart deployment/inference-gateway -n ai-inference
```

请求时带上：

```powershell
curl.exe -H "X-API-Key: replace-with-a-long-random-token" `
  -H "Content-Type: application/json" `
  -d '{"message":"hello","max_tokens":8}' `
  http://127.0.0.1:9001/chat
```

`/live`、`/health`、`/metrics` 故意保持无认证，供探针和 Prometheus 使用。
Secret 不要提交到 Git。

## 已知边界

- HPA 未生效：集群没有 metrics-server，`ScalingActive=False`。
- GPU 未由 Kubernetes 调度：没有 NVIDIA device plugin。
- vLLM 仍是单实例，模型服务本身没有高可用。
- 没有 TLS、认证、NetworkPolicy、租户配额。
- 没有长时间 soak test、内存泄漏分析或持续负载 p99。
- TensorRT-LLM 未测量，见 [`../docs/RUNTIME_COMPARISON.md`](../docs/RUNTIME_COMPARISON.md)。

## 文件

| 文件 | 作用 |
|---|---|
| `namespace.yaml` | 命名空间 |
| `configmap.yaml` | 模型名、上游地址、并发/超时/重试参数 |
| `deployment.yaml` | 2 副本、探针、滚动策略、安全上下文 |
| `service.yaml` | ClusterIP 入口 |
| `pdb.yaml` | `minAvailable: 1` |
| `hpa.yaml` | CPU HPA 清单（未生效） |
| `observability/prometheus.yaml` | Prometheus、RBAC、按 Pod 抓取 |
| `benchmark/loadgen-job.yaml` | 100 请求 / 并发 4 Service 压测 |
| `benchmark/loadgen-kill-job.yaml` | 压测中强杀 Pod 的 300 请求测试 |
