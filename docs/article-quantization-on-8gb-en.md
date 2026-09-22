# Quantizing a 4B model onto 8 GB: a reproducible chain of tradeoffs

*What I actually learned was not the throughput numbers. It was that I had to retract three of my own conclusions, and each retraction came from measurement rather than intuition.*

**Setup:** Windows + WSL2 (Ubuntu 22.04) · RTX 5060 8 GB · vLLM 0.29.0 · PyTorch 2.13.0+cu130 · CUDA runtime 13.0

---

## 1. The constraints that drive everything else

One consumer 8 GB card. One 4B vision-language model (Qwen3.5-4B). And a requirement that matters more than the numbers: the result has to be something **someone else can run**.

Three constraints decide every tradeoff below.

1. **VRAM.** The BF16 checkpoint is 8.701 GiB — larger than the card. Native vLLM will not start. This is not a tuning problem; quantization is mandatory.
2. **KV cache and CUDA Graph compete for the same memory.** Whatever quantization frees up, context length, concurrency, and static graph capture take back. This is why `max-num-seqs` ends up at 16, and why the best-performing configuration is not the one I ship.
3. **WSL2 is not native Linux.** It produces two specific problems, one of which I later discovered was my own misunderstanding.

**Two models, don't mix them.** The project uses **Qwen3.5-4B** as the delivery target (quantization, quality evaluation, speculative decoding, offline bundle) and **Qwen3-0.6B** purely as a load for characterizing the engine. Measuring how continuous batching converts concurrency into throughput requires a load that does not become the bottleneck itself — a 4B model on 8 GB cannot reach high concurrency. The two sets of numbers do not explain each other. I initially got this wrong in my own docs and had to fix it, because quoting the 0.6B throughput as the delivery model's performance is the easiest mistake to make.

---

## 2. Two quantization paths, and an evaluation that can prove itself fair

**FP8_BLOCK:** weights to FP8, activations quantized dynamically at inference. No calibration text needed.

**W4A16 asymmetric INT4 with AWQ:**

- Calibration on C-Eval `dev`, 128 fixed-seed samples, max length 512 tokens
- W4A16_ASYM, group size 128, AWQ duo scaling, 20 scaling candidates
- **Per-`Qwen3_5DecoderLayer` calibration**, CPU offload
- 200 linear weights stored as packed INT4
- Embeddings, vision module, `lm_head`, and small sensitive projections in linear attention kept at **BF16**

Resulting sizes:

| Model | Size | vs BF16 |
|---|---:|---:|
| BF16 | 8.701 GiB | — |
| Third-party FP8 | 5.281 GiB | −39.3% |
| Self-made FP8 v3 | 5.281 GiB | −39.3% |
| **Self-made W4A16 INT4-AWQ** | **3.568 GiB** | **−59.0%** |

**The evaluation design matters more than the quantization.** The two easy ways to cheat a quantization benchmark are letting the calibration set overlap the eval set, and letting sampling parameters drift. Both are pinned here:

- C-Eval `val`, **frozen at 200 questions**, 52 subjects
- The question set is frozen and its sample SHA-256 recorded (`8df8746b…c941`), so anyone can verify it is the same set
- **Calibration on `dev`, evaluation on `val`, disjoint splits** — no leakage
- Prompts, question order, answer parsing, `temperature=0`, thinking disabled, max 8 output tokens — all fixed
- The three quantized models served sequentially through vLLM; BF16, whose checkpoint does not fit in 8 GB, ran layer-wise on CPU with Transformers at fixed batch size 4 as a quality baseline only

That last point comes with a limit I have to state: **BF16 latency is not comparable to a GPU-resident vLLM model**, because it ran under entirely different conditions. I only use it as a quality reference.

---

## 3. First surprise: identical scores do not mean equivalent models

| Model | Accuracy | Per-question agreement with BF16 | Fixed BF16 errors | Broke BF16 correct answers |
|---|---:|---:|---:|---:|
| BF16 reference | 141/200 (70.5%) | 100.0% | — | — |
| Third-party FP8 | 141/200 (70.5%) | 96.5% | 3 | 3 |
| Self-made FP8 v3 | 141/200 (70.5%) | **98.0%** | 2 | 2 |
| Self-made INT4-AWQ v1 | 141/200 (70.5%) | **87.0%** | 11 | 11 |

**All four models score exactly 141/200.**

Read only that column and you conclude "INT4 is lossless, ship it." That conclusion is wrong.

Read the next column: **INT4 agrees with BF16 on only 87.0% of questions.** That is 26 questions where it picks a different option. It breaks 11 questions BF16 got right while fixing 11 BF16 got wrong — the errors cancel in the total.

And 200 multiple-choice questions cannot establish equivalence in the first place. The Wilson 95% interval around 141/200 is roughly **63.84%–76.39%** — wide enough to swallow any realistic difference.

> **Identical totals only mean "no accuracy difference observed on these 200 questions." They do not mean the models are equivalent.** Behavioral change has to be measured as its own metric. **Per-question agreement is that metric.**

This distinction is the most useful thing the project produced, because it answers the question that actually matters: is it safe to swap a quantization scheme in production? FP8, yes (98% agreement). INT4, not without evaluating on your own data first (87%).

---

## 4. What broke, and why

Ordered by how likely you are to hit the same thing.

### 4.1 Transformers 5.14 swallows the `forward` signature

AWQ calibration failed with a missing-argument error. The cause: Transformers 5.14's `force_accelerate_hooks` decorator does not preserve the original signature of `Qwen3_5GatedDeltaNet.forward`, so AWQ caches `hidden_states` as a nested `kwargs` and cannot match it on replay.

Fix: **restore only the signature metadata at runtime inside the quantization script** — no patching of the third-party package, no change to the forward computation. The script stays portable and survives a transformers upgrade.

This is worth filing upstream: reproducible, with a clear blast radius (anyone calibrating AWQ on Qwen3.5-family Gated DeltaNet layers hits it).

### 4.2 `max_num_seqs=256` cannot capture CUDA Graph

vLLM's default `max_num_seqs` is 256. Qwen3.5's Gated DeltaNet state cache blows the memory budget at that value and graph capture fails.

`--max-num-seqs 16` is enough for these experiments and captures successfully. **This is the binding parameter constraint on this machine** — every performance number below sits under it.

### 4.3 MTP plus CUDA Graph does not fit

With multi-token prediction enabled alongside CUDA Graph, the computed **KV cache budget is −1.03 GiB.** Negative. It will not start. This is what forces the shipped bundle onto a more conservative N-gram configuration.

### 4.4 FlashInfer sampler needs `nvcc`

vLLM's FlashInfer sampler JIT-compiles a CUDA kernel on first use, which needs the full CUDA Toolkit — I only have the runtime driver. Since these experiments decode greedily at `temperature=0`, the fused top-k/top-p sampler is unnecessary, so I disable it (`VLLM_USE_FLASHINFER_SAMPLER=0`).

---

## 5. Second surprise: the "platform limitation" was a default-off switch

I was wrong about this one for a while.

My experiment notes said:

> WSL cannot run vLLM's V2 model runner because it requires UVA

So I had been setting `VLLM_USE_V2_MODEL_RUNNER=0` to fall back to the older V1 runner. **That conclusion was false.**

Upstream, vLLM has PR **#54655** (2026-09-01, "Fall back to the V1 model runner where UVA is unavailable") — and **WSL2 is the reported scenario.** Its description states that pinned memory *is* supported on WSL2; it is simply disabled by default behind a switch.

The source comment (`vllm/platforms/cuda.py:302-309`) is unambiguous:

```python
302-                )
303-                return False
304-            # On compatible WSL2 kernels, pinned memory is supported but
305-            # disabled by default. Enable it via VLLM_WSL2_ENABLE_PIN_MEMORY=1.
306-            import vllm.envs as envs
308:            return envs.VLLM_WSL2_ENABLE_PIN_MEMORY
309-        return True
```

Measured:

| Check | Result |
|---|---|
| Kernel version | 6.18.33.2, far above the 4.19.121 threshold |
| `is_pin_memory_available()`, switch unset | `False` |
| `is_pin_memory_available()`, `VLLM_WSL2_ENABLE_PIN_MEMORY=1` | **`True`** |
| Server started with the switch | log shows `Using V2 Model Runner` |

**V2 does run.** Then the honest question became whether it is faster. A/B, same conditions, only the runner differs:

| Config | Concurrency | Output throughput | TTFT P50 | TPOT P50 |
|---|---:|---:|---:|---:|
| A · V1 runner | 1 | 102.35 tok/s | 73.64 ms | 9.26 ms |
| A · V1 runner | 4 | 332.74 tok/s | 252.66 ms | 10.13 ms |
| B · V2 + pinned | 1 | 102.04 tok/s | 74.24 ms | 9.28 ms |
| B · V2 + pinned | 4 | 332.57 tok/s | 252.38 ms | 10.13 ms |

**−0.3% and −0.1%.** Indistinguishable.

So the truth was a third option I had not considered: **V2 is available, selectable, and makes no measurable difference on this workload.**

My error was not choosing the wrong runner — either choice was fine. My error was **conflating an availability question with a performance question, and describing a configurable switch as a platform limitation.**

> **Takeaway:** when you read "platform X does not support Y," first check whether Y is a **default-off switch.** The two cases are very different: one means the road is closed, the other means change a setting.

---

## 6. Third surprise: my own numbers would not reproduce

This one I stumbled into, and it consumed the most time.

### 6.1 The gap

While running the A/B above, I checked numbers recorded a few days earlier. They did not match.

| | Concurrency 1 | Concurrency 4 |
|---|---:|---:|
| Recorded 2026-09-17 | 109.12 | 359.71 |
| Re-measured 2026-09-22 | 102.35 | 332.74 |
| Delta | **−6.2%** | **−7.5%** |

I verified the parameters element by element: `num_prompts=16`, `max_concurrency=1/4`, `request_rate=inf`, `completed=16`, `failed=0`, and total output tokens of 2048 on both sides. **Identical.**

### 6.2 Rule out noise first

Three consecutive rounds inside one server session:

| | Three samples | Mean | Range | Std dev |
|---|---|---:|---:|---:|
| Concurrency 1 | 101.48 / 102.70 / 102.49 | 102.22 | 1.2% | 0.66 |
| Concurrency 4 | 333.35 / 331.47 / 332.07 | 332.29 | 0.6% | 0.96 |

Within-session range of 0.6%–1.2% against a 6–7% gap. **Noise cannot explain it.** This step mattered: it closed off "it might just be variance" as an excuse.

### 6.3 Record the environment, then kill the thermal hypothesis

I added GPU state sampling to the benchmark scripts — SM and memory clocks, power draw, power limit, temperature, pstate, throttle reasons — captured before and after every measurement.

Result:

```
throttle_reasons = 0x0000000000000000   ← no throttling of any kind
temperature      49–64 °C
power draw       78–105 W (limit 145 W)
SM clock         2535 → 2752 MHz (rising, not falling)
```

**"Thermal throttling caused the drift" is dead.** No throttling, cool card, plenty of power headroom, and the clock went *up* over the session.

This is worth emphasizing: **recording your measurement environment does not always produce an answer — often it produces an elimination.** Without these samples I would have kept guessing about cooling.

### 6.4 The real clue: the change is not uniform

After re-measuring the full set in one batch, the pattern appeared:

| Config | Concurrency 1 | Concurrency 4 |
|---|---:|---:|
| Third-party FP8 | **+0.7%** | **+2.6%** |
| Self-made FP8 v3 | −7.2% | −5.7% |
| Self-made INT4-AWQ | −5.6% | −7.2% |
| Qwen3-0.6B | −7.6% / −6.1% / +2.2% / −7.3% | |

**Third-party FP8 barely moved. Both self-made models dropped 6–7% together.**

If the whole machine had simply slowed down, third-party FP8 would have dropped too. So this is not a single environmental factor — it correlates with the **quantization kernel path**: both self-made models run through compressed-tensors + Marlin, third-party FP8 does not.

**I still do not know the cause.** The candidate is a difference in kernel autotuning or warmup state between batches, but I have not verified it, so I do not present it as a conclusion.

### 6.5 Which invalidated one of my relative claims

Re-running three rounds per config:

| Model | Concurrency | Three samples | Mean | Range |
|---|---:|---|---:|---:|
| Third-party FP8 | 1 | 71.5 / 72.2 / 72.4 | 72.02 | 1.3% |
| Third-party FP8 | 4 | 256.6 / 257.0 / 256.9 | 256.83 | 0.1% |
| Self-made FP8 v3 | 1 | 72.8 / 72.7 / 72.7 | 72.76 | 0.1% |
| Self-made FP8 v3 | 4 | 257.1 / 257.5 / 257.4 | 257.33 | 0.1% |
| Self-made INT4 | 1 | 102.9 / 103.0 / 103.0 | 102.99 | 0.1% |
| Self-made INT4 | 4 | 334.1 / 332.9 / 334.7 | 333.90 | 0.6% |

I had written that **"self-made FP8 v3 is slightly faster than third-party FP8."** It is not:

- Concurrency 1: 72.76 vs 72.02, **+1.0%** (within-session range 0.1%)
- Concurrency 4: 257.33 vs 256.83, **+0.2%** (within-session range 0.1%)

Two independent measurement rounds agree: **they are equivalent.** That sentence is deleted. I can now say "equivalent" — I cannot say "slightly faster," and I cannot say "slightly slower."

INT4's advantage, by contrast, holds: **+43.0% at concurrency 1, +30.0% at concurrency 4** over third-party FP8, far outside the dispersion.

**A side benefit:** the selection rationale got cleaner. It used to be "self-made FP8 v3 has better quality and is also slightly faster." Now it is **purely quality** (98.0% vs 96.5% per-question agreement). A claim that stands on one reason beats a claim that stands on two vague ones.

### 6.6 The part I did not expect: single runs are unreliable within the same day

Earlier the same day, a single run of self-made FP8 v3 at concurrency 4 gave **246.66.** Three rounds later the same day averaged **257.33.** That is **4.3% off, against its own 0.1% within-session range.**

Separately, the first round of a session tends to read low (third-party FP8 at concurrency 1: first round 71.5, next two 72.2 and 72.4) — a warmup effect.

> **The rule I adopted: any performance figure quoted externally is the mean of at least 3 rounds per configuration, measured within one batch.**

I had only repeat-tested a single configuration before concluding one round was enough. This 4.3% outlier corrected me.

---

## 7. How the parameters were chosen

Parameter values matter less than the fact that **each one traces back to a measurement or a memory constraint.** Three examples.

### 7.1 `--max-num-seqs=16` instead of the default 256

From §4.2: Qwen3.5's Gated DeltaNet state cache blows the budget at 256 and graph capture fails. 16 captures successfully.

Being able to answer "why 16" with "because 256 fails and 16 is the tested working value" is a different level from "that's the default."

### 7.2 Speculative decoding depth: deeper is not faster

| Config | Acceptance rate | Concurrency 4, relative to baseline |
|---|---:|---:|
| No MTP | — | 1.00× |
| MTP-1 | 98.35% | 1.65× |
| MTP-3 | 96.26% | 2.82× |
| **MTP-4 (recommended)** | 95.16% | 3.22× |
| **MTP-5 (peak)** | 94.12% | **3.37×** |
| MTP-6 | 90.83% | 2.95× |
| MTP-8 | 79.40% | 2.59× |

(Measured within one fair comparison batch, so the ratios hold even though absolute values are batch-relative.)

Acceptance rate falls monotonically with depth (98.35% → 79.40%), throughput peaks at MTP-5 and declines, and TTFT degrades sharply from MTP-6 on — MTP-8 exceeds 1 second of TTFT while gaining only 0.32% over MTP-6. No practical value.

**The criterion is not "deeper is faster"; it is the product of acceptance rate and memory budget.** Weighing TTFT, throughput, and acceptance together, MTP-4 is the recommendation.

### 7.3 The one that matters: the best configuration is not the shippable configuration

MTP is the single biggest win in the whole system — 3.37× — and **the shipped bundle does not enable it.**

Reason: 8 GB cannot hold the production 2048 context, 16 sequences, CUDA Graph, and MTP simultaneously. Combined, the computed KV cache budget is **−1.03 GiB.**

So the system ships as two configurations:

- **Delivery bundle** → conservative N-gram, stability first
- **MTP** → available as a low-concurrency, 1024-context performance configuration

> Lots of people tune a service right up to the edge of not starting, because the peak number looks better. **Separating "peak capability" from "shipping configuration," and stating the cost of each, is the engineering judgment.**

---

## 8. Engine baseline: batching is a tradeoff, not a ceiling

This section characterizes the **engine**, not a model. The load is Qwen3-0.6B, small enough to reach concurrency 64 without hitting the VRAM wall.

| Client concurrency | Output throughput | TTFT P50 | TPOT P50 | Success |
|---:|---:|---:|---:|---:|
| 1 | 265.76 tok/s | 14.95 ms | 3.67 ms | 100% |
| 4 | 898.85 tok/s | 18.02 ms | 4.32 ms | 100% |
| 16 | 2,811.97 tok/s | 33.84 ms | 5.47 ms | 100% |
| 64 | 5,693.04 tok/s | 94.50 ms | 10.48 ms | 100% |

(Single run. This section's conclusion depends on the trend, not the exact values.)

From concurrency 1 to 64, **total throughput rises 21.4×, while per-request TPOT rises 2.9× and TTFT rises 6.3×.**

**"Accepts 64 concurrent requests" and "64 users each keep single-user latency" are two different claims.** Capacity planning has to treat this curve as a tradeoff, not a limit.

---

## 9. From "it runs" to "you can run it"

Half of inference engineering is serving and delivery.

**Gateway** (FastAPI, sitting between clients and vLLM):

- Browser chat UI, non-streaming `POST /chat`, SSE streaming `POST /chat/stream` (with TTFT and end-to-end latency)
- Request-ID propagation, Pydantic validation, Unicode sanitization
- **Four independent timeout classes** (connect/read/write/pool); upstream error translation; upstream cancellation when the client disconnects
- Bounded concurrency and queueing with **HTTP 429 backpressure**
- Split `/live` (process) and `/health` (upstream dependency); `/gateway/status` for in-flight and queued counts
- Prometheus counters, gauges, latency histograms; single-line JSON application logs
- **9 pytest cases requiring neither a model nor a GPU**, covering success, validation failure, upstream timeout/disconnect/HTTP error, capacity rejection, and queue timeout
- Non-root Docker image

**Offline bundle:** model, the vLLM/PyTorch/CUDA userspace environment, gateway, Compose file, one-click scripts, and SHA-256 manifests — **7.49 GiB** total, fully verified on a clean Docker Desktop install (image import, GPU check, model startup, browser chat).

**Those 9 offline tests are what I am most satisfied with.** No GPU, no model, running in seconds, and they cover the real failure paths. That is worth far more than "it works on my machine."

---

## 10. What I deleted from my own documentation

This section says more than the results do.

| Claim removed | Why |
|---|---|
| "WSL cannot run the V2 runner because it requires UVA" | Measured: pinned memory is supported on WSL2, just default-off. The original claim turned a configurable switch into a platform limitation |
| "Self-made FP8 v3 is slightly faster than third-party FP8" | Two independent rounds show equivalence (+1.0% / +0.2%, both inside within-session range) |
| "Cross-session drift is most likely due to GPU clock/thermal state" | Recorded GPU state shows no throttling, 49–64 °C, power far below limit — hypothesis eliminated |
| Leading the project README with Qwen3-0.6B throughput | It is a test load, not the delivery model. Leading with the biggest number was a positioning error |
| Quoting single-run figures in external material | Measured a single run deviating 4.3% from its own 3-round mean |

**Writing the retractions down matters more than writing the results down.** A document containing only successful conclusions gives the reader no way to tell whether the author understood the system or got lucky. **What you removed, and why, is the signal.**

---

## 11. What I would do differently

1. **Record the measurement environment from day one**, not after an unexplained discrepancy appears. GPU state sampling costs almost nothing and the hypotheses it eliminates are expensive.
2. **Run 3 rounds per config from the first measurement.** Saving two minutes up front cost hours of figuring out which numbers were even usable.
3. **When you read "platform X does not support Y," check for a switch first.** This one habit prevents an entire round of wrong technical decisions.
4. **Any metric that can cancel out needs a companion consistency metric.** Accuracy lies; per-question agreement does not.
5. **Track "shipping configuration" and "peak configuration" separately from the start.** Do not discover at delivery time that the optimum does not fit.

---

## Appendix: where the raw data lives

Every number here traces back to a file in the repository. Nothing is quoted from memory.

- Per-question evaluation results (4 models × 200 questions): `benchmark/eval/`
- Frozen question set and sample hash: `benchmark/eval/ceval-val-200.json`
- All raw performance JSON (concurrency sweeps, long context, speculative decoding, repeat comparisons): `benchmark/results/`
- GPU state records: `benchmark/results/rebaseline/gpu-state.csv`
- Quantization and evaluation entry points: `quantize_fp8_block.py`, `quantize_int4_awq.py`, `ceval_quality_eval.py`
- Repeat-measurement scripts: `scripts/rebuild_baseline.sh`, `scripts/repeat_bench_quant.sh`
- Full investigation log and correction history: `docs/`
