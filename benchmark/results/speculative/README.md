# Qwen3.5-4B-FP8 推测解码测评

日期：2026-09-15

## 环境

- GPU：NVIDIA GeForce RTX 5060（8 GiB）
- 模型：Qwen3.5-4B-FP8
- vLLM：0.29.0
- 系统：WSL `photo3d`

## 公平测试条件

- 随机输入长度：256 tokens
- 固定输出长度：256 tokens
- `temperature=0`，`seed=42`
- 并发 1：8 个请求
- 并发 4：16 个请求
- 所有公平对照均使用：V1 Model Runner、PyTorch sampler、eager mode、
  `max_model_len=1024`、`max_num_seqs=4`、
  `max_num_batched_tokens=1024`、`gpu_memory_utilization=0.85`

使用兼容配置的原因：当前 WSL 环境的 V2 Model Runner 无法使用 UVA；
FlashInfer sampler 首次 JIT 需要未安装的 `nvcc`；MTP 开启 CUDA Graph 后，
KV Cache 预算为 -1.03 GiB，无法在 8 GiB 显存中启动。

> **更正（2026-09-22 实测）**：上面第一条「WSL 环境的 V2 Model Runner 无法使用 UVA」**不准确，已作废**。
>
> 实测：WSL2 上 pinned memory 是**受支持**的，只是 vLLM 默认关闭（`vllm/platforms/cuda.py:302-309`，注释原文 "pinned memory is supported but disabled by default"）。设 `VLLM_WSL2_ENABLE_PIN_MEMORY=1` 后服务端日志显示 `Using V2 Model Runner`，且性能与 V1 runner 等价（并发 1 差 -0.3%，并发 4 差 -0.1%）。
>
> **但本次扫描的结果不受影响，不需要重跑**：所有对照组都使用同一个 V1 runner，被测变量是 MTP 深度，对照关系成立。错的只是给出的理由。
>
> 另外两条仍然成立：FlashInfer sampler 需要未安装的 `nvcc`；MTP + CUDA Graph 的 KV Cache 预算为 -1.03 GiB，8 GiB 装不下。
>
> 详见根目录 [`docs/wsl2-runner-verification.md`](../../../docs/wsl2-runner-verification.md)。

## 结果

| 配置 | 接受率 | 并发1 TPS | 并发1 TTFT | 并发1 TPOT | 并发4 TPS | 并发4 TTFT | 并发4 TPOT |
|---|---:|---:|---:|---:|---:|---:|---:|
| 无 MTP | — | 27.92 | 174.52 ms | 35.27 ms | 104.26 | 248.60 ms | 37.54 ms |
| MTP-1 | 98.35% | 44.45 | 377.72 ms | 21.10 ms | 172.47 | 503.79 ms | 21.20 ms |
| MTP-2 | 96.66% | 62.64 | 247.39 ms | 15.06 ms | 218.41 | 507.16 ms | 15.94 ms |
| MTP-3 | 96.26% | 80.30 | 210.72 ms | 11.67 ms | 293.60 | 426.94 ms | 11.81 ms |
| MTP-4 | 95.16% | 97.05 | 218.54 ms | 9.49 ms | 335.37 | 447.85 ms | 9.93 ms |
| MTP-5 | 94.12% | 102.08 | 221.13 ms | 8.97 ms | **351.37** | 453.38 ms | 9.45 ms |
| MTP-6 | 90.83% | 107.18 | 260.87 ms | 8.34 ms | 307.48 | 690.99 ms | 10.00 ms |
| MTP-8 | 79.40% | **107.52** | 264.14 ms | 8.30 ms | 269.94 | 1061.81 ms | 9.55 ms |

TPS 为服务总输出吞吐（tokens/s）。TTFT 越低，开始回答越快；TPOT 越低，
完成整段回答越快。推测解码会成批返回已接受的 tokens，因此普通 ITL
不能直接代表肉眼看到的连续流畅度。

## 结论

1. MTP 在此模型上有效。公平配置下，MTP-5 将并发 4 总吞吐从
   104.26 提升到 351.37 tokens/s，约为基线的 3.37 倍。
2. 最佳多人吞吐是 MTP-5；MTP-6 开始回落，MTP-8 的 TTFT 已超过 1 秒。
3. 单用户吞吐在 MTP-6 后基本封顶。MTP-8 只比 MTP-6 快 0.32%，
   却有更差的接受率和流式间隔，因此没有实际使用价值。
4. 综合推荐 MTP-4：比 MTP-5 少约 4.6% 的并发吞吐，但首 token 和流式间隔
   略好，推测深度也更保守。只追求总吞吐时使用 MTP-5。
5. 当前 8 GiB 显存无法同时保留正式服务的 2048 上下文、16 序列、
   CUDA Graph 和 MTP。日常稳定服务暂时保持无 MTP；MTP 作为低并发、
   1024 上下文的性能配置。

## 当前状态

测评结束后已恢复原稳定服务：2048 上下文、16 序列、Prefix Cache、
Chunked Prefill、CUDA Graph，不启用 MTP。
