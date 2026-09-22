# Kubernetes 第一课：部署轻量推理网关

这一阶段只把 FastAPI 网关交给 Kubernetes 管理，不把 4B 模型放进集群。目标是先分清 Pod、Deployment、Service、ConfigMap 和探针各自解决的问题。

## 对象关系

```text
浏览器
  │  本机端口转发 localhost:9001
  ▼
Service/inference-gateway（稳定入口）
  │  按标签选择 Pod
  ▼
Deployment/inference-gateway（期望副本数 = 2）
  │  创建和替换
  ▼
Pod/gateway（运行 ai-inference-gateway:v1）
  │
  ├─ 从 ConfigMap 读取模型名、上游地址和并发参数
  └─ /live 接受 startup、readiness、liveness 探测
```

- **Pod** 是 Kubernetes 最小调度单位，这里装一个网关容器。Pod 被替换后名字和 IP 都可能改变。
- **Deployment** 保存“我要 2 个这样的 Pod”这个期望状态，并负责扩缩容、重建与滚动更新。
- **Service** 根据标签找到当前 Pod，提供不随 Pod 更换而改变的集群内地址。
- **ConfigMap** 保存非敏感配置；以后修改参数无需重做镜像。
- **Probe** 让 Kubernetes 知道容器是否已启动、是否可接流量、是否需要重启。

## 为什么暂时不把模型放进来

4B 模型会同时引入 GPU device plugin、显存、镜像/模型制品、启动时间和调度问题。第一课若全部一起上，任何失败都很难判断是 Kubernetes 还是 CUDA/vLLM。先用轻量网关镜像把控制面概念跑通，下一阶段再接模型。

## 前置条件

1. Docker Desktop 正在运行。
2. Docker Desktop 中已创建并启动一个单节点 Kubernetes 集群。
3. `kubectl config current-context` 输出 `docker-desktop`，且 `kubectl get nodes` 显示 `Ready`。
4. 本机已有镜像 `ai-inference-gateway:v1`。

当前清单使用 `imagePullPolicy: Never`，故意禁止从网络拉取同名镜像：它只允许使用本机已经验收过的镜像，也能暴露“集群是否看得到本地镜像”这一问题。

Docker Desktop 当前创建的是 kind 集群。宿主 Docker 中存在镜像，不代表 kind 节点自己的 containerd 中也存在它。首次部署前可在 PowerShell 里直接导入镜像流：

```powershell
docker save ai-inference-gateway:v1 | docker exec -i desktop-control-plane ctr -n k8s.io images import -
docker exec desktop-control-plane ctr -n k8s.io images list | Select-String ai-inference-gateway
```

这里直接传输字节流，不再先 `docker cp` 到节点的 `/tmp`；后者在当前 Docker Desktop 版本中曾出现“复制报告成功但节点内找不到文件”的情况。

## 部署与观察

在 Windows PowerShell 中运行：

```powershell
cd E:\AI-Inference-Lab
kubectl apply -k .\k8s
kubectl rollout status deployment/inference-gateway -n ai-inference --timeout=120s
kubectl get pods,deploy,svc -n ai-inference -o wide
```

然后启动端口转发（这个窗口需要保持打开）：

```powershell
kubectl port-forward service/inference-gateway 9001:9000 -n ai-inference
```

浏览器打开 <http://localhost:9001/>。这里使用 9001，是因为 Docker Compose 版网关已经占用本机 9000；Kubernetes Service 内部仍监听 9000。此时网页和 `/live` 应可访问；如果宿主机没有启动 vLLM，真正发送对话会提示上游不可用，这是当前阶段的预期现象。

当前 Deployment 使用两个网关副本。Service 根据标签把新连接转发到其中一个健康 Pod。两个网关仍然共用宿主机上同一个 vLLM，因此这里增加的是网关层的可用性和入口处理能力，不是 GPU 推理算力。另需注意，`kubectl port-forward service/...` 会选中一个后端 Pod 建立调试通道，不适合用来验证 Service 的负载分配；负载分配测试应从集群内部访问 Service。

另开一个 PowerShell 观察自动恢复：

```powershell
kubectl get pods -n ai-inference -w
```

记下当前 Pod 名称，再删除它：

```powershell
kubectl delete pod -n ai-inference -l app.kubernetes.io/name=inference-gateway
```

Deployment 会自动创建新 Pod，使副本数重新回到 2。这不是“旧容器复活”，而是控制器发现实际状态少于期望状态后创建了替代品。

## 常用诊断

```powershell
kubectl describe pod -n ai-inference -l app.kubernetes.io/name=inference-gateway
kubectl logs -n ai-inference deployment/inference-gateway
kubectl get events -n ai-inference --sort-by=.lastTimestamp
```

若状态是 `ErrImageNeverPull`，表示 Kubernetes 节点看不到 Docker 引擎里的本地镜像；不要把 `imagePullPolicy` 改成盲目联网拉取。对当前单节点学习环境，使用上面的字节流导入命令即可；实际多节点环境通常通过镜像仓库分发。

## 本课验收

- 能用自己的话解释 Pod、Deployment、Service 的区别。
- 删除 Pod 后能看到 Deployment 自动补回一个新 Pod。
- 能从 `describe`、`logs`、`events` 三类证据定位一次失败。
- 能解释为什么当前 readiness 使用 `/live`，以及完整推理服务接入后为什么应考虑切换到检查上游的 `/health`。
