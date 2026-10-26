# Evaluation evidence

This directory contains the current INT4 recheck, the frozen baselines used for
the quantization comparison, and the paired statistics that tie them together.

## Current recheck

| File | What |
|---|---|
| `int4-ceval-val-200.json` | 200-question C-Eval, current INT4 build |
| `int4-quant-quality.json` | 32-case local quant-quality smoke |
| `int4-vs-v1-agreement.json` | Paired statistics: current INT4 vs INT4 v1 |
| `ceval-val-200.json` | frozen C-Eval manifest |
| `freeform-cases.json` | free-form regression cases |

## Frozen reference comparison

These are retained because the current INT4 result is compared with the INT4 v1
baseline, and because the FP8 sizes and BF16 agreement numbers come from this
set. They are reference baselines, not reruns of the current serving tree.

| File | What |
|---|---|
| `bf16-reference-ceval-val-200.json` | BF16 reference |
| `third-party-fp8-ceval-val-200.json` | third-party FP8 |
| `self-fp8-v3-ceval-val-200.json` | locally produced FP8 v3 |
| `self-int4-awq-v1-ceval-val-200.json` | locally produced INT4-AWQ v1 |
| `quantization-final-comparison.csv` | size, accuracy, agreement and throughput summary |

## Current numbers

- C-Eval: **142/200 (71.0%)**, Wilson 95% **64.4–76.8%**;
- current INT4 vs INT4 v1: **99.5% agreement** (95% Wilson **97.2–99.9%**),
  **1 fixed / 0 broken**, McNemar exact p **1.0000**, Cohen's κ **0.993**;
- quant-quality: **25/32 (78.1%)**, strict = relaxed;
- reference comparison: BF16, third-party FP8, local FP8 v3 and local INT4 v1
  each score **141/200**; INT4 v1 agrees with BF16 on **87.0%** of questions;
- model sizes: BF16 **8.701 GiB**, FP8 **5.281 GiB**, INT4-AWQ **3.568 GiB**.

Reference paired statistics (BF16 baseline):

| Model | Accuracy (95% Wilson) | Agreement with BF16 (95% Wilson) | Fixed / broken | McNemar p | Cohen's κ |
|---|---:|---:|---:|---:|---:|
| Third-party FP8 | 141/200 = 70.5% (63.8–76.4%) | 96.5% (93.0–98.3%) | 3 / 3 | 1.0000 | 0.953 |
| Self FP8 v3 | 141/200 = 70.5% (63.8–76.4%) | 98.0% (95.0–99.2%) | 2 / 2 | 1.0000 | 0.973 |
| Self INT4-AWQ v1 | 141/200 = 70.5% (63.8–76.4%) | 87.0% (81.6–91.0%) | 11 / 11 | 1.0000 | 0.826 |

Regenerate the reference table with:

```bash
python tools/quality_stats.py
```

## Reproduce the current recheck

```bash
python ceval_quality_eval.py run \
  --manifest benchmark/eval/ceval-val-200.json \
  --base-url http://127.0.0.1:8000/v1 \
  --model Qwen3.5-4B-INT4-AWQ \
  --label int4 \
  --output benchmark/eval/int4-ceval-val-200.json

python quant_quality_eval.py run \
  --base-url http://127.0.0.1:8000/v1 \
  --model Qwen3.5-4B-INT4-AWQ \
  --label int4 \
  --output benchmark/eval/int4-quant-quality.json
```

The 200-question set is small; per-question agreement and the paired statistics
are the primary signal, not a single accuracy total.
