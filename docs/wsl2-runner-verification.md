# 验证：WSL2 上到底能不能跑 vLLM V2 model runner

## 为什么要做这个验证

`INT4-AWQ实验记录.md` 里记了一条结论：

> WSL 当前不支持 vLLM V2 runner 所需的 UVA，且没有完整 CUDA Toolkit 供 FlashInfer sampler 首次 JIT，所以使用
> `VLLM_USE_V2_MODEL_RUNNER=0`、`VLLM_USE_FLASHINFER_SAMPLER=0`

FlashInfer sampler 那半条没问题。**UVA 这半条可能不完整。**

上游证据：

- `vllm-project/vllm` 有 PR **#54655**（2026-09-01，标题 “Fall back to the V1 model runner where UVA is unavailable”），关联 issue #54652 / #47292 / #47387，**WSL2 就是被报告的那个场景**。
- 该 PR 的说明指出：平台报告没有 pinned host memory 时 `is_uva_available()` 为假，但 V2 runner 仍被默认选中，于是在 `init_device` 处直接抛 `RuntimeError: UVA is not available`。
- **WSL2 的问题在于 pinned memory 被一个开关默认关掉了**（关掉的原因是历史上发现它有轻微性能回归），而不是 UVA 在 WSL2 上绝对不可用。社区通行的解法是 `VLLM_WSL2_ENABLE_PIN_MEMORY=1`，从而**保留 V2 runner**，而不是退回 V1。

换句话说：设 `VLLM_USE_V2_MODEL_RUNNER=0` 能跑通，但它是在用**旧 runner** 换可用性。如果 V2 其实能跑，那么现有 benchmark 数字是在 V1 runner 上测出来的。

**但必须实测才能下结论。** 同一个 PR 的说明里明确写了 WSL2 上的 pinned memory 本身存在“小幅性能回归”，所以 V2 + pinned memory 是否更快，方向不确定。

这个验证的意义不只是性能：如果结论要写进对外文章和仓库文档，它必须是对的。

---

## 两组对照

| 组 | 环境变量 | 目的 |
|---|---|---|
| **A · 现状基线** | `VLLM_USE_V2_MODEL_RUNNER=0` | 复现你在用的配置，作为性能对照 |
| **B · 新方案** | `VLLM_WSL2_ENABLE_PIN_MEMORY=1`（不设 `VLLM_USE_V2_MODEL_RUNNER`） | 看 V2 runner 能否起来、性能是否变化 |

（原计划的「对照 C · 强制 V2」已不需要——第 0 步实测确认开关生效，可以直接观察 B 组是否走 V2。）

**唯一变量必须是 runner 与 pinned memory。** 模型、`--max-model-len`、`--max-num-seqs`、`--gpu-memory-utilization`、prefix caching、chunked prefill、压测参数全部保持不变，否则数字不可比。

---

## 第 0 步结论（已于 2026-09-22 实测完成）

在本机（内核 `6.18.33.2-microsoft-standard-WSL2`、vLLM 0.29.0、torch 2.13.0+cu130）实测结果：

| 检查项 | 结果 |
|---|---|
| 内核版本 | 6.18.33.2，远高于门槛 4.19.121 ✅ |
| `VLLM_WSL2_ENABLE_PIN_MEMORY` 开关是否存在 | **存在** ✅ |
| 不带开关时 `is_pin_memory_available()` | `False` |
| 带 `VLLM_WSL2_ENABLE_PIN_MEMORY=1` 时 | **`True`** ✅ |

`vllm/platforms/cuda.py` 第 302–309 行的源码给出了直接依据：

```python
302-                )
303-                return False
304-            # On compatible WSL2 kernels, pinned memory is supported but
305-            # disabled by default. Enable it via VLLM_WSL2_ENABLE_PIN_MEMORY=1.
306-            import vllm.envs as envs
308:            return envs.VLLM_WSL2_ENABLE_PIN_MEMORY
309-        return True
```

> **结论修正**：`INT4-AWQ实验记录.md` 中「WSL 当前不支持 vLLM V2 runner 所需的 UVA」的表述**不准确**。
> 正确表述是：**在兼容内核的 WSL2 上 pinned memory 是受支持的，但 vLLM 默认关闭，需要显式设置 `VLLM_WSL2_ENABLE_PIN_MEMORY=1`。**
>
> 另外，`is_pin_memory_available()` 返回 `False` 正是 PR #54655 描述的触发条件——这说明遇到的是**已知的上游问题**，而不是 WSL2 的架构限制。

剩下的唯一未知项是**性能**：V2 runner 能否正常启动，以及它相对 V1 runner 更快还是更慢。进入下一步。

---

## 第 1 步：一键 A/B 对照（推荐）

```bash
cd /mnt/e/AI-Inference-Lab
bash scripts/verify_v2_runner.sh
```

这个脚本会依次：启动服务 → 等健康 → 抓启动日志里的 runner 行 → 压测并发 1 与 4 → 停服务，A/B 各做一遍，最后打印对照表格。

**它会独占 GPU 并占用 8000 端口，全程约 10–20 分钟。**跑之前请确认没有别的 vLLM 实例在运行（脚本会先检查并拒绝）。

也可以只跑单边：

```bash
bash scripts/verify_v2_runner.sh A     # 只跑现状 V1 runner
bash scripts/verify_v2_runner.sh B     # 只跑新方案 V2 + pinned
```

服务端日志会分别存到 `benchmark/results/runner-verify/v1runner-server.log` 和 `v2runner-server.log`，其中的 runner 版本行就是判定用的直接证据。

---

## 第 2 层结论（已于 2026-09-22 实测完成）

**V2 runner 在 WSL2 上确实能跑。**服务端日志里的直接证据：

```text
(EngineCore pid=1798) INFO 09-22 16:21:55 [gpu_worker.py:429] Using V2 Model Runner
```

**但性能与 V1 runner 没有可测差异：**

| 配置 | 并发 | 输出吞吐 | TTFT P50 | TPOT P50 |
|---|---:|---:|---:|---:|
| A · V1 runner | 1 | 102.35 tok/s | 73.64 ms | 9.26 ms |
| A · V1 runner | 4 | 332.74 tok/s | 252.66 ms | 10.13 ms |
| B · V2 + pinned | 1 | 102.04 tok/s | 74.24 ms | 9.28 ms |
| B · V2 + pinned | 4 | 332.57 tok/s | 252.38 ms | 10.13 ms |

两次差值：并发 1 为 **-0.3%**，并发 4 为 **-0.1%**，都在噪声内。

> **净结论**：上游提到的「WSL2 pinned memory 轻微性能回归」在这个负载上**观测不到**。
> 两个 runner 在 RTX 5060 + INT4-AWQ 上等价。
>
> 所以原结论的错误不是"选错了 runner"（事实上选哪个都一样），而是**把可用性问题和性能问题混为一谈**，并且把一个可配置项描述成了平台限制。这是两种不同性质的工程判断误差。
>
> **这处错误在仓库里出现了两次，均已加带日期的更正块：**
> - 原 `docs/int4-awq-experiment-log.md` 的「vLLM 运行配置与兼容处理」一节。该文件已删除：它记录的模型与量化脚本路径是 WSL 时期的 `/mnt/e/...`，现已全部失效，更正后的结论保留在本文。
> - [`benchmark/results/speculative/README.md`](../benchmark/results/speculative/README.md) 的「公平测试条件」一节
>
> 两处都**不需要重跑实验**：相关对照组的被测变量分别是量化方案和 MTP 深度，runner 在所有组里都一致，对照关系有效——错的只是给出的理由。这一点在更正工程结论时很重要，别把"理由错了"误当成"数据废了"。

---

## ⚠️ 新暴露的问题：历史基线数字当前复现不出来

同一次实测里发现了一件更要紧的事：

| | 并发 1 | 并发 4 |
|---|---:|---:|
| 2026-09-17 记录（`qwen35-int4-awq-self-compiled-*.json`） | 109.12 | 359.71 |
| 2026-09-22 实测（同参数、同模型、同脚本口径） | 102.35 | 332.74 |
| 差异 | **-6.2%** | **-7.5%** |

已逐项核对 `num_prompts=16`、`max_concurrency=1/4`、`request_rate=inf`、`completed=16`、`failed=0`，两边完全一致；输出 token 总数也都是 2048，吞吐换算无误。

也就是说：**参数相同，结果差 6–7%。**

可能的原因（尚未验证，按可能性排序）：

1. **GPU 时钟 / 温度 / 环境负载不同**——两次测量相隔 5 天，消费级卡在这类环境下漂 5–8% 并不罕见。
2. **服务预热状态不同**——历史那次的服务可能已经先跑过量化和质量评测请求，缓存与显存分配器状态更"熟"。
3. **双峰效应**——这台机器此前出现过同一配置在两组延迟之间交替的现象，单次测量本就不可靠。

**在弄清这一点之前，不要把任何一组数字写进对外材料。** 结论本身（V2 ≈ V1）不受影响，因为那是同一次会话内背靠背测出来的；但**绝对数值的基线需要重新确定**。

### 重复性实测结果（2026-09-22 完成）

同一次启动的服务内连跑 3 轮：

| | 三个样本 | 均值 | 极差 | 样本标准差 |
|---|---|---:|---:|---:|
| 并发 1 | 101.48 / 102.70 / 102.49 | 102.22 | 1.23（1.2%） | 0.66 |
| 并发 4 | 333.35 / 331.47 / 332.07 | 332.29 | 1.88（0.6%） | 0.96 |

**判读：极差远小于 2%，且稳定偏离历史值（并发 1 差 -6.3%，并发 4 差 -7.6%），且没有出现双峰。**

结论有两层，都很重要：

1. **当次测量本身是精确的**——同会话内标准差不到 1%，CV 约 0.6%。所以这不是"测量噪声大"，不能拿噪声解释那 6-7%。
2. **偏差来自跨会话的环境漂移**。同一天内两次独立测量（A/B 对照的 102.35，重复压测的 102.22）只差 0.1%；而相隔 5 天的两次测量差 6-7%。

> **方法论结论（应写进对外材料）**：在这套消费级 GPU + WSL2 环境里，**只有同一会话内的比较是有效的**。跨天的绝对数值不可直接对比。任何对外引用的数字，要么同批产出，要么明确标注测量日期与同批范围。

最可能的原因是 GPU 时钟/功耗/温度状态在两次测量时不同。为了以后不用再靠猜，重定基线脚本已加入每次压测前后的 GPU 状态采样（SM/显存时钟、功耗、功耗墙、温度、pstate、降频原因）。

### 解决方式

```bash
cd /mnt/e/AI-Inference-Lab
bash scripts/rebuild_baseline.sh            # 全部，约 15-25 分钟
bash scripts/rebuild_baseline.sh qwen3      # 只重测 Qwen3-0.6B 并发 sweep
bash scripts/rebuild_baseline.sh qwen35     # 只重测三个 Qwen3.5-4B 量化模型
```

在一次会话内把对外要用到的全部性能数字重测一遍，输出「新旧基线对照」表格和 GPU 状态记录。这样得到的一组数字彼此可比，可以直接替换对外材料里的旧值。

> **注意模型不是同一个**：吞吐曲线用的是 **Qwen3-0.6B**（模型够小，能把并发拉到 64 而不撞显存），量化三向对比用的是 **Qwen3.5-4B**。两者不能互相解释，对外引用时务必写清是哪个。

### 同批重测结果（2026-09-22 完成）—— 出现了比漂移更麻烦的情况

| 配置 | 并发 1 | 并发 4 |
|---|---:|---:|
| Qwen3.5-4B 第三方 FP8 | +1.1% | +1.6% |
| Qwen3.5-4B 自制 FP8 v3 | -6.8% | -9.6% |
| Qwen3.5-4B 自制 INT4-AWQ | -5.8% | -8.3% |
| Qwen3-0.6B（并发 1/4/16/64） | -7.6% / -6.1% / +2.2% / -7.3% | |

**关键发现：变化不均匀。**第三方 FP8 几乎没动，两个自制量化模型一起掉了 6-10%。如果只是"机器慢了一档"，第三方也该跟着掉。所以这不是单一环境因子，而是与量化内核路径相关（两个自制模型都走 compressed-tensors + Marlin）。

**已经排除热降频。**当次 GPU 状态记录：`throttle_reasons = 0x0000000000000000`、温度 49–63 °C、功耗 78–106 W（上限 145 W）、SM 时钟在会话中从 2535 升到 2752 MHz。**"变热降频"这个解释被数据否掉了**——这正是把 GPU 状态记录加进脚本的价值，它替我们排除了一条错误的假设。

**相对关系受影响：**

| 相对关系 | 2026-09-17 | 2026-09-22 |
|---|---:|---:|
| 自制 INT4 ÷ 第三方 FP8（并发 1） | 1.53× | 1.42× |
| 自制 INT4 ÷ 第三方 FP8（并发 4） | 1.44× | 1.30× |
| 自制 FP8 v3 ÷ 第三方 FP8（并发 4） | 1.09× | **0.97×** |

- INT4 优势从 +52.6% / +43.7% 收窄到 +42.1% / +29.7%（方向不变，仍是大优势）
- **「自制 FP8 v3 吞吐略高于第三方 FP8」被推翻**，相关表述已从根 README、一页纸、eval README 三处删除

**尚未确定的原因**：最可能是不同批次之间量化内核的自动调优与预热状态不同。候选解释，未验证。

### 重复对照结果（2026-09-22 完成）—— 差异是真实的

三个量化模型各连跑 3 轮 c1/c4，批内极差极小：

| 模型 | 并发 | 三个样本 | 均值 | 批内极差 |
|---|---:|---|---:|---:|
| 第三方 FP8 | 1 | 71.5 / 72.2 / 72.4 | 72.02 | 1.3% |
| 第三方 FP8 | 4 | 256.6 / 257.0 / 256.9 | 256.83 | 0.1% |
| 自制 FP8 v3 | 1 | 72.8 / 72.7 / 72.7 | 72.76 | 0.1% |
| 自制 FP8 v3 | 4 | 257.1 / 257.5 / 257.4 | 257.33 | 0.1% |
| 自制 INT4 | 1 | 102.9 / 103.0 / 103.0 | 102.99 | 0.1% |
| 自制 INT4 | 4 | 334.1 / 332.9 / 334.7 | 333.90 | 0.6% |

**判读结果：**

1. **批内极差 0.1%–1.3%，测量本身极其精确。**所以那 6–7% 的跨批复现差异**不是噪声**，是真实的。
2. **「自制 FP8 v3 吞吐略高于第三方 FP8」被彻底删除。**两轮独立测量结论一致——**两者吞吐等价**（+1.0% / +0.2%，都在批内极差以内）。以后只能说"等价"，不能说"略快"或"略慢"。
3. **INT4 相对第三方 FP8 的优势稳固**：+43.0% / +30.0%，批内极差 ≤0.6%，远大于离散度。
4. **第三方 FP8 跨批基本不变**（+0.7% / +2.6%），两个自制模型跨批低 6–7%——差异确实与量化内核路径相关，不是整机变慢。

**顺带发现一个方法论要点：单次测量不可靠，即使同一天也不行。**当天早些时候的单次测量里，自制 FP8 v3 并发 4 得到 246.66，而随后 3 轮均值是 257.33，**偏离 4.3%，远超其 0.1% 的批内极差**。另外首批测量普遍略低（第三方 FP8 并发 1 首轮 71.5 vs 后两轮 72.2/72.4），像是预热效应。

> **规矩：对外引用的性能数字，同批次内每配置至少跑 3 轮取均值。**

**对外材料采用了哪一版数字**：根 README、`docs/project-notes.md`、`benchmark/eval/README.md`、两份一页纸都已更新为上面这组 3 轮均值。`benchmark/eval/quantization-final-comparison.csv` 由 `scripts/build_quantization_csv.py` 从 `benchmark/results/rbq-*-r{1,2,3}-c{1,4}.json` 重建，CI 以 `--check` 校验它与原始数据一致，已不再是手工维护的遗留项。

**仍待收敛的问题**：为什么两个自制模型跨批低 6–7%。已排除热降频，候选是内核自动调优/预热状态差异，未验证。这属于"已知但不阻塞对外"的问题——因为对外数字已经统一到同一批次，不再混用。

---

## 附：手动执行方式（脚本出问题时的退路）

需要自己控两个终端时，用下面这套。

### 终端 1 · 起服务

**对照 A · 现状基线**

```bash
cd /mnt/e/AI-Inference-Lab
source /root/.venvs/ai-inference-bin/activate
env VLLM_USE_V2_MODEL_RUNNER=0 VLLM_USE_FLASHINFER_SAMPLER=0 \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  vllm serve /mnt/e/Desktop/qwen3.5/model/qwen3.5-4b-int4-awq-self-v1 \
    --served-model-name Qwen3.5-4B-INT4-AWQ \
    --host 0.0.0.0 --port 8000 \
    --language-model-only --skip-mm-profiling \
    --enable-prefix-caching --enable-chunked-prefill \
    --max-model-len 2048 --max-num-seqs 16 --gpu-memory-utilization 0.80
```

**对照 B · 新方案**（唯一差别在 env）

```bash
env VLLM_WSL2_ENABLE_PIN_MEMORY=1 VLLM_USE_FLASHINFER_SAMPLER=0 \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  vllm serve ...（其余完全相同）
```

**每组都要抄下启动日志里那一行**——它会明确写用的是 V1 还是 V2。这一行是判定的直接证据。

### 终端 2 · 压测

```bash
cd /mnt/e/AI-Inference-Lab
bash scripts/bench_qwen35_int4.sh v1runner-int4     # 对照 A 时用这个前缀
bash scripts/bench_qwen35_int4.sh v2runner-int4     # 对照 B 时用这个前缀
```


---

## 记录表（请填好贴回）

| 项 | A · 现状（V1） | B · 新方案 |
|---|---|---|
| 服务是否启动成功 | | |
| 启动日志里的 runner | | |
| 启动耗时（粗略） | | |
| 启动后 `nvidia-smi` 显存占用 | | |
| 并发 1 输出吞吐 tok/s | | |
| 并发 4 输出吞吐 tok/s | | |
| 并发 4 TTFT P50 | | |
| 并发 4 TPOT P50 | | |
| 结果 JSON 文件名 | | |

历史参考值（V1 runner，INT4-AWQ compiled）：**并发 1 = 109.12 tok/s，并发 4 = 359.71 tok/s**。

---

## 结案

原本留了三种可能（B 更快 / B 更慢 / B 起不来），实测落在**第四种**：

- **B 能起，且与 A 等价**——并发 1 差 -0.3%，并发 4 差 -0.1%，都在噪声内。

所以这个问题的正确答案既不是"WSL 不支持"，也不是"该换用 V2"，而是：**V2 可用、可选、但在这个负载上没有差别；原结论的错误在于把一个可配置项描述成了平台限制。**详见上面「第 2 层结论」。

顺带产出了两个额外结果：

1. 把 GitHub PR #54655 / 社区解法（`VLLM_WSL2_PIN_MEMORY`）与实际版本行为对齐，确认本机 vLLM 0.29.0 已具备该开关。
2. 在核对旧数字时发现**跨批次不可复现**，并进一步发现变化不均匀、与量化内核路径相关，同时用 GPU 状态记录排除了热降频。这条排查链比原问题本身更有价值。

**可复用的经验（比结论本身更值钱）**：

- 遇到"某平台不支持 X"，先查它是不是一个**默认关闭的开关**，再下结论。
- 记录的测量环境（时钟、功耗、温度、降频原因）能在事后**排除假设**，即使不能给出原因。这次它替我们否掉了热降频，省下一轮瞎猜。
- 反过来，当结论的理由被推翻时，要先问"数据本身还成立吗"。本次三处结论里，只有一处（自制 FP8 v3 吞吐略快）需要删除，另两处只需改理由。
