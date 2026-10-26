# Evaluation evidence

The clean branch keeps only the current evaluation files and the frozen
manifests needed to reproduce them.

## Current results

| File | What |
|---|---|
| `int4-ceval-val-200.json` | 200-question C-Eval, INT4 |
| `int4-quant-quality.json` | 32-case local quant-quality smoke |
| `ceval-val-200.json` | frozen C-Eval manifest |
| `freeform-cases.json` | free-form regression cases |

## Current numbers

- C-Eval: **142/200 (71.0%)**;
- 99.5% per-question agreement with the earlier INT4 report;
- quant-quality: **25/32 (78.1%)**, strict = relaxed.

## Reproduce

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

The 200-question set is small; treat per-question agreement as the primary
signal, not a single accuracy total.
