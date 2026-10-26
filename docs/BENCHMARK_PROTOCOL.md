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

Evidence: `benchmark/results/int4-r3-c*.json`.

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
- per-question agreement, Wilson interval, McNemar, Cohen's κ;
- 32-case local quant-quality smoke is a separate regression set.

## Rules

- Do not merge results with different protocols.
- Do not quote a mock-upstream run as model performance.
- Do not quote a 16-prompt microbenchmark as a capacity plan.
- Record the image/tag, GPU, driver, runtime, and raw path with every result.
