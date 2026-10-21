# Qwen3.5-4B W4A16 INT4-AWQ 实验记录

日期：2026-09-17

## 产物

- 源模型：`/mnt/e/Desktop/qwen3.5/model/qwen3.5-4b`
- INT4 模型：`/mnt/e/Desktop/qwen3.5/model/qwen3.5-4b-int4-awq-self-v1`
- 量化脚本：`/mnt/e/AI-Inference-Lab/quantize_int4_awq.py`
- 校准集：C-Eval dev，固定随机种子抽取 128 条，最大长度 512 tokens
- 方案：W4A16_ASYM，group size 128，AWQ duo scaling，20 个缩放候选
- 流水线：逐个 `Qwen3_5DecoderLayer` 校准，CPU offload

## 与上次 FP8 的区别

上次 FP8_BLOCK 不需要校准文本，权重转为 FP8，激活在推理时动态 FP8 量化。这次 AWQ 会实际执行校准前向，依据激活统计寻找低误差缩放，再把大多数 Linear 权重静态压成非对称 INT4；激活仍为 BF16。

Embedding、视觉模块、`lm_head`、线性注意力中的小型敏感投影保留 BF16。

## 文件大小

| 模型 | 大小 |
|---|---:|
| BF16 | 8.701 GiB |
| 第三方 FP8 | 5.281 GiB |
| 自制 FP8 | 5.281 GiB |
| 自制 INT4-AWQ | 3.568 GiB |

INT4-AWQ 比 BF16 小约 59%，比 FP8 小约 32%。共有 200 个线性权重以 packed INT4 保存。

## 质量回归（32题）

| 模型 | 正确 | 与 BF16 回答完全一致 |
|---|---:|---:|
| BF16 | 27/32 | 32/32 |
| 第三方 FP8 | 28/32 | 29/32 |
| 自制 FP8 v3 | 25/32 | 26/32 |
| 自制 INT4-AWQ v1 | 25/32 | 24/32 |

INT4 没有灾难性退化，但数学、逻辑比 BF16 更容易受量化误差影响。当前 32 题只是快速回归集，不足以作为最终模型能力结论。

## 性能（256 input / 128 output，16 requests）

| 模式 | 并发 | 输出吞吐 | TTFT 中位数 | TPOT 中位数 |
|---|---:|---:|---:|---:|
| INT4 eager | 1 | 32.74 tok/s | 79.54 ms | 30.15 ms |
| INT4 eager | 4 | 123.54 tok/s | 252.29 ms | 30.96 ms |
| INT4 compiled | 1 | 109.12 tok/s | 67.72 ms | 8.66 ms |
| INT4 compiled | 4 | 359.71 tok/s | 231.04 ms | 9.39 ms |

此前同条件附近的自制 FP8 compiled 约为单并发 78.4 tok/s、4 并发 272.8 tok/s。INT4 本次分别约快 39% 和 32%。这些数字只适用于当前 RTX 5060、vLLM 0.29、短上下文配置。

## vLLM 运行配置与兼容处理

WSL 当前不支持 vLLM V2 runner 所需的 UVA，且没有完整 CUDA Toolkit 供 FlashInfer sampler 首次 JIT，所以使用：

```bash
export VLLM_USE_V2_MODEL_RUNNER=0
export VLLM_USE_FLASHINFER_SAMPLER=0
```

> **更正（2026-09-22 实测）**：上面那句「WSL 当前不支持 vLLM V2 runner 所需的 UVA」**不准确，已作废**。
>
> 实测结论：WSL2 上 pinned memory 是**受支持**的，只是 vLLM 默认关闭（`vllm/platforms/cuda.py:302-309`，注释原文 "pinned memory is supported but disabled by default"）。设置 `VLLM_WSL2_ENABLE_PIN_MEMORY=1` 后 `is_pin_memory_available()` 由 `False` 变 `True`，服务端日志显示 `Using V2 Model Runner`。
>
> 但**性能与 V1 runner 等价**：并发 1 差 -0.3%，并发 4 差 -0.1%，都在噪声内。所以当时的取舍结果没错，错的是理由——把一个可配置项说成了平台限制。
>
> 同一批实测还发现本文件的性能数字当前复现不出来（并发 1 差 -6.2%、并发 4 差 -7.5%，参数完全一致），原因待查。
>
> 完整证据与复现方式见 [`docs/wsl2-v2-runner-验证指引.md`](wsl2-runner-verification.md)。

`VLLM_USE_FLASHINFER_SAMPLER=0` 这半条结论仍然成立（本机确实没有完整 CUDA Toolkit）。

Qwen3.5 的 Gated DeltaNet 状态缓存限制使默认 `max_num_seqs=256` 无法捕获 CUDA Graph。本机采用 `--max-num-seqs 16`，足够当前并发实验。

vLLM 检测到 `compressed-tensors` 并使用 `MarlinLinearKernel for CompressedTensorsWNA16`，说明推理确实运行 packed INT4 权重，没有解压回 BF16。

## 量化期间修复的问题

Transformers 5.14 的 `force_accelerate_hooks` 装饰器没有保存 `Qwen3_5GatedDeltaNet.forward` 的原始签名。AWQ 因此把 `hidden_states` 错误缓存成嵌套 `kwargs`，重放时报缺少参数。量化脚本在运行时只恢复签名元数据，不修改第三方包，也不改变 forward 计算。

## 当前结论

这是一份成功、可运行且性能不错的 W4A16 INT4-AWQ 模型。它更适合显存受限、吞吐优先的部署实验；若优先追求质量稳定，当前第三方 FP8 仍是更稳妥的默认模型。下一步应使用规模更大、贴近真实用途的独立评测集，判断是否值得继续优化 AWQ 校准语料和忽略层策略。
