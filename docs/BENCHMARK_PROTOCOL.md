# Benchmark protocol

Comparability is a property of the protocol, not the filename.

## Direct vLLM

- backend: OpenAI-compatible vLLM 0.29.0
- input: 256 tokens
- output: 128 tokens
- prompts per run: 16
- warmups: 2
- temperature: 0
- concurrency: 1 and 4
- compiled mode
- repetitions: **1** per concurrency in the current evidence

The current `int4-c1.json` / `int4-c4.json` files are single runs. The frozen
INT4 v1 reference reported 333.9 tok/s at c=4; do not treat the current 309.55
as a controlled regression until the run is repeated.

Evidence: `benchmark/results/int4-c*.json`.

## Gateway soak

- URL: `POST /chat`
- concurrency: 4
- output tokens: 32
- closed loop for the requested duration
- telemetry every 10 s: active, waiting, GPU memory, GPU utilization
- after the loop, wait for admission to drain before checking `/gateway/status`

Evidence: `benchmark/results/soak-c4-7200s-telemetry.json` and
`benchmark/results/soak-c4-600s-metrics-final.json`.

## Quality

- C-Eval `val`, 200 frozen questions, 52 subjects;
- temperature 0, thinking disabled, max 8 output tokens;
- current INT4 recheck: 142/200, Wilson 95% 64.4–76.8%;
- current INT4 vs INT4 v1: 99.5% agreement (95% Wilson 97.2–99.9%),
  1 fixed / 0 broken, McNemar exact p 1.0000, Cohen's κ 0.993;
- BF16/FP8/INT4-v1 reference comparison uses the same 200-question manifest;
- 32-case local quant-quality smoke is a separate regression set.

Paired statistics are generated with `python tools/quality_stats.py` from the
frozen reference files in `benchmark/eval/`. The current-vs-v1 result is stored
in `benchmark/eval/int4-vs-v1-agreement.json`.

## Rules

- Do not merge results with different protocols.
- Do not quote a mock-upstream run as model performance.
- Do not quote a 16-prompt microbenchmark as a capacity plan.
- Do not quote a single run as a repeated measurement.
- Record the image/tag, GPU, driver, runtime, and raw path with every result.
