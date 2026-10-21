# 项目详细记录：单卡 vLLM 推理工程实践

这份文档是项目的详细记录，门面摘要见[根 README](../README.md)。

在 **NVIDIA GeForce RTX 5060 8GB** 上完成的一条本地推理工程链路：

`vLLM 服务 → 并发压测 → KV Cache/调度 → FP8/INT4 量化 → 推测解码 → FastAPI 网关 → Docker 离线交付`

> **关于路径命名**：这个项目早期按"学习计划第几周"组织，目录曾叫 `week1`、`week6_api`。
> 现在已全部改为**按功能命名**——`week1` 这一层被取消（它实际涵盖全部模块，时间标签本身就是错的），
> 内容按功能提升到仓库根；网关目录改为 `gateway/`。
> **约定：仓库内不再出现以时间（第几周/第几天）命名的路径。**

## 当前状态

| 模块 | 状态 | 证据 |
|---|---|---|
| vLLM 与核心机制 | 完成 | `chat.py`、`scripts/start_server.sh`、Prefix Cache/Chunked Prefill demo |
| 并发与性能压测 | 完成 | `benchmark/concurrency_report.xlsx`、曲线图、原始 JSON |
| FP8 / INT4-AWQ 量化 | 完成 | 两个量化脚本、自制模型、`INT4-AWQ实验记录.md` |
| 量化质量评测 | 完成 | C-Eval `val` 200 题、四模型逐题结果、精度 × 体积 × 吞吐总表 |
| KV Cache、调度与推测解码 | 完成 | 参数 sweep、Prefix Cache、Chunked Prefill、MTP/N-gram 报告 |
| Python 生产网关 | 完成 | SSE、超时、错误、探针、背压、指标、JSON 日志、19 个 pytest |
| Docker 离线交付 | 完成并实机验收 | 模型、两个镜像、Compose、一键脚本、SHA-256 校验 |
| 成本模型 | 完成 | `tools/cost_calculator.py` + 5 个单元测试 |
| 正式网关测试、结构化日志 | 完成 | 19 个离线 pytest；关键应用事件为单行 JSON |
| Kubernetes 网关层 | 2026-10-21 已验证 | 2 副本、探针、PDB、零停机滚动/回滚、Prometheus；100 请求 0 错误，压测中强杀 Pod 的 300 请求 0 错误；GPU 调度未验证 |

## 关键结果

所有数字都只适用于当前硬件、软件版本和对应测试条件，不应直接外推到其他 GPU 或长上下文业务。

### 1. Qwen3-0.6B 并发基线

固定 256 input / 128 output、64 个请求：

| 客户端并发 | 输出吞吐 | TTFT P50 | TTFT P95 | TPOT P50 | 成功率 |
|---:|---:|---:|---:|---:|---:|
| 1 | 265.76 tok/s | 14.95 ms | 15.51 ms | 3.67 ms | 100% |
| 4 | 898.85 tok/s | 18.02 ms | 23.64 ms | 4.32 ms | 100% |
| 16 | 2,811.97 tok/s | 33.84 ms | 41.88 ms | 5.47 ms | 100% |
| 64 | 5,693.04 tok/s | 94.50 ms | 120.18 ms | 10.48 ms | 100% |

（本表为 2026-09-22 同批重测数据；2026-09-17 的原值及变化幅度见根 README 的「关于数字的可比性」。）

![并发与延迟曲线](../benchmark/throughput_latency_curve.png)

结论：连续批处理让总吞吐随并发显著上升，但每个请求的 TPOT 和 TTFT 同时变差；“能接收 64 个请求”不等于 64 个请求都保持单用户延迟。

### 2. Qwen3.5-4B 量化结果

模型体积：

| 模型 | 大小 |
|---|---:|
| BF16 | 8.701 GiB |
| 第三方 FP8 | 5.281 GiB |
| 自制 FP8 | 5.281 GiB |
| 自制 W4A16 INT4-AWQ | 3.568 GiB |

正式质量评测使用固定的 C-Eval `val` 200 题，覆盖 52 个科目；量化校准使用 `dev`，与评测集分离。四个模型采用同一题目、提示词、题序、答案解析和采样参数：

| 模型 | 正确率 | 与 BF16 逐题答案一致率 | 修正 BF16 错题 | 损失 BF16 对题 |
|---|---:|---:|---:|---:|
| BF16 参考 | 141/200（70.5%） | 100.0% | — | — |
| 第三方 FP8 | 141/200（70.5%） | 96.5% | 3 | 3 |
| 自制 FP8 v3 | 141/200（70.5%） | 98.0% | 2 | 2 |
| 自制 INT4-AWQ v1 | 141/200（70.5%） | 87.0% | 11 | 11 |

四个模型总分相同，不等于完全等价：INT4 有 26 道题的答案不同于 BF16，行为变化明显大于 FP8。200 道单选题也不能代表自由文本、代码和长上下文能力。完整方法、限制、原始报告和机器可读总表见 [量化最终对比](../benchmark/eval/README.md)。此前的 32 题结果只保留作探索性回归，不再作为最终选型依据。

固定 256 input / 128 output、16 个请求、编译模式：

| 模型 | 并发 | 输出吞吐（3 轮均值） | 批内极差 | TTFT P50 | TPOT P50 |
|---|---:|---:|---:|---:|---:|
| 第三方 FP8 | 1 | 72.02 tok/s | 1.3% | 47.92 ms | 13.57 ms |
| 第三方 FP8 | 4 | 256.83 tok/s | 0.1% | 159.49 ms | 14.41 ms |
| 自制 FP8 v3 | 1 | 72.76 tok/s | 0.1% | 48.11 ms | 13.46 ms |
| 自制 FP8 v3 | 4 | 257.33 tok/s | 0.1% | 159.90 ms | 14.39 ms |
| 自制 INT4-AWQ | 1 | 102.99 tok/s | 0.1% | 72.24 ms | 9.21 ms |
| 自制 INT4-AWQ | 4 | 333.90 tok/s | 0.6% | 251.73 ms | 10.07 ms |

（本表为 2026-09-22 同一会话内每配置连跑 3 轮的均值。跨批次不可复现的问题见根 README 的「关于数字的可比性」。）

当前选择：更看重贴近 BF16 的行为时使用自制 FP8 v3——**理由是质量（一致率 98.0% vs 96.5%），不是速度**，两者吞吐在本次批内极差内等价（未做正式统计检验）；在 8GB 显存上更看重模型体积和吞吐时使用自制 INT4-AWQ（相对第三方 FP8 并发 1 +43.0%、并发 4 +30.0%），并接受其更大的逐题行为变化。详见 [量化最终对比](../benchmark/eval/README.md)和 [INT4-AWQ 实验记录](int4-awq-experiment-log.md)。

### 3. 推测解码

公平实验中，MTP-5 的并发 4 输出吞吐由 104.26 提升到 351.37 tok/s；综合 TTFT、吞吐和接受率更推荐 MTP-4。8GB 显存无法同时保留正式服务的较长上下文、较高并发、CUDA Graph 和激进 MTP，因此稳定部署包使用更保守的 N-gram 配置。详见 [推测解码报告](../benchmark/results/speculative/README.md)。

## 生产网关

`gateway/` 位于客户端与 vLLM OpenAI 兼容接口之间，已经实现：

- 浏览器聊天页；
- 非流式 `POST /chat` 与 SSE `POST /chat/stream`；
- 请求 ID、参数校验、Unicode 清理；
- 连接/读取/写入/连接池超时；
- 上游错误转换和客户端断开取消；
- 有界并发与队列、HTTP 429 背压；
- `/live`、`/health`、`/gateway/status`；
- Prometheus `/metrics`；
- 单行 JSON 应用日志；
- 19 个不依赖真实模型的 pytest，覆盖正常、校验失败、上游超时/断连/HTTP 错误、容量拒绝、排队超时、连接重试、探针身份、可选 API Key 认证与按身份限流；
- 非 root Docker 镜像与 Compose。

详见 [网关 README](../gateway/README.md)。

## 目录导航

| 路径 | 用途 |
|---|---|
| `chat.py` | 命令行多轮聊天，自动裁剪历史并处理 Unicode |
| `real_chat_load.py` | 多虚拟用户、多轮真实对话压测 |
| `prefix_cache_demo.py` | Prefix Cache 冷/热前缀对照 |
| `chunked_prefill_demo.py` | 长 prefill 与持续 decode 混合负载 |
| `quantize_fp8_block.py` | FP8_BLOCK 模型生成脚本 |
| `quantize_int4_awq.py` | 使用 C-Eval 校准的 W4A16 INT4-AWQ PTQ |
| `quant_quality_eval.py` | 32 题快速质量回归与报告比较 |
| `ceval_quality_eval.py` | 准备、断点续跑和比较正式 C-Eval `val` 200 题评测 |
| `benchmark/eval/ceval-val-200.json` | 已冻结的 200 题清单、数据来源与样本哈希 |
| `benchmark/eval/README.md` | 四模型正式质量、体积与性能结论及原始证据索引 |
| `benchmark/eval/quantization-final-comparison.csv` | 可继续分析或制图的量化三向总表 |
| `scripts/` | vLLM 启动、基线压测、推测解码实验脚本 |
| `benchmark/results/` | 原始 benchmark JSON、日志和指标快照 |
| `gateway/` | FastAPI 网关、网页、Dockerfile 与验证脚本 |
| `k8s/` | 第 7 模块第一课：网关 Deployment、Service、ConfigMap 与探针 |
| `tests/` | 成本工具与 C-Eval 协议单元测试；网关测试位于 `gateway/test_gateway.py` |

## 可复现环境

- Windows + WSL2（Ubuntu 22.04）
- NVIDIA GeForce RTX 5060 8GB
- vLLM 0.29.0
- PyTorch 2.13.0+cu130
- CUDA runtime 13.0
- Python 虚拟环境：`/root/.venvs/ai-inference-week1`
  （**这是唯一保留了 `week` 字样的地方**。它是仓库之外的运行时环境名，把 venv 目录改名会破坏
  `bin/` 下 console script 的 shebang 绝对路径（`vllm`、`pip` 都会失效），需要重建整个环境才能改。
  评估后认为不值得，因此保留并在此说明——不是遗漏。）

本机 Qwen3.5 模型位于 `/mnt/e/Desktop/qwen3.5/model/`。启动脚本仍引用该本地路径；公开仓库时只提交脚本、配置和报告，不提交模型权重。

## 独立离线部署包

完整交付目录位于：

`E:\Desktop\Qwen3.5-4B-INT4-Docker-Offline-20260918`

它包含模型、vLLM/PyTorch/CUDA 用户态环境、网页网关、Docker Compose、一键脚本和校验文件，总大小约 7.49 GiB。已在全新的 Docker Desktop 环境中完成镜像导入、GPU 检查、模型启动和网页对话验证。

## 成本计算

成本计算器直接读取 vLLM benchmark JSON 的实测 `output_throughput`。下面的 `1 CNY/GPU-hour` 只是演示输入，不代表真实云价：

```bash
python tools/cost_calculator.py \
  --benchmark-json benchmark/results/qwen35-int4-awq-self-compiled-c4.json \
  --gpu-hour-price 1 \
  --currency CNY
```

本地硬件模式需要整机购置价、有效寿命、有效利用率、整机墙上功耗和电价：

```bash
python tools/cost_calculator.py \
  --tokens-per-second 333.90 \
  --hardware-price 8000 \
  --lifetime-years 3 \
  --utilization 0.5 \
  --power-watts 220 \
  --electricity-price-per-kwh 0.6 \
  --currency CNY
```

这是容量成本估算，不包含空闲波动、网络、存储、人工、税费、冗余和利润；不能直接冒充云 API 的完整报价。

## 下一阶段

第 1–6 模块已经完成验收，第 7 模块的**网关层**已于 2026-10-21 在 Docker Desktop Kubernetes 上实测：2 副本、Service、探针、PDB、零停机滚动/回滚、Prometheus 按 Pod 抓取；100 请求 0 错误，压测中强杀 Pod 的 300 请求 0 错误。GPU 调度未验证——`nvidia.com/gpu` 探针因集群没有 device plugin 而 Pending。完整证据见 [`K8S_VERIFICATION.md`](K8S_VERIFICATION.md)。

当前仍待完成的是 Linux GPU 节点 + NVIDIA device plugin 的稳定 in-cluster vLLM，以及 TensorRT-LLM 同协议对比；Prometheus/Grafana、OpenTelemetry、SLO、HPA（mock）和 10 分钟 soak 已完成。网关镜像 `v0.2.3` 已重建并验证；若重新发布离线包，需要刷新镜像与 SHA-256 校验值。
