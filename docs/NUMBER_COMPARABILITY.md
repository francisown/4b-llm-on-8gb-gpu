# Why the numbers in this repository do not compare across batches

This page exists because one rule decides which figures are quotable:

> **Any performance figure quoted externally is the mean of at least 3 runs per
> configuration, measured within one batch.**

The rule was not chosen for elegance. It came out of a failed reproduction.

## How the rule came about

Figures recorded on 2026-09-17 were re-measured on 2026-09-22 with identical
parameters (`num_prompts`, concurrency, input/output lengths, `completed`,
`failed` all verified element by element). They did not match — and **they did
not fail to match uniformly**:

| Configuration | Concurrency 1 | Concurrency 4 |
|---|---:|---:|
| Qwen3.5-4B **third-party FP8** | **+0.7%** | **+2.6%** |
| Qwen3.5-4B self-made FP8 v3 | −7.2% | −5.7% |
| Qwen3.5-4B self-made INT4-AWQ | −5.6% | −7.2% |
| Qwen3-0.6B (concurrency 1/4/16/64) | −7.6% / −6.1% / +2.2% / −7.3% | |

(Numbers are 3-run means. A positive percentage means the new value is higher.
**This does not establish which batch is "more correct"** — only that the old
values do not reproduce in the current environment.)

**Third-party FP8 barely moved; both self-made quantized models came in 6–7%
lower.** If the whole machine had simply slowed down, third-party FP8 would
have dropped too. So this is not a single environmental factor — it correlates
with the quantization kernel path (both self-made models run
compressed-tensors + Marlin).

**Hypothesis eliminated: thermal throttling.** The recorded GPU state was
`throttle_reasons = 0x0000000000000000` (no throttling of any kind), 49–64 °C,
78–105 W against a 145 W limit, and an SM clock that rose from 2535 to
2752 MHz over the session. **"The GPU throttled" is dead.**

**Cause still unknown:** the candidate is a difference in kernel autotuning or
warmup state between batches. **Unverified**, so not used as a conclusion.

## The difference is real, not a one-off fluctuation

Repeated measurement settled it:

| Configuration | Within-session range over 3 samples |
|---|---:|
| Third-party FP8 (concurrency 1 / 4) | 1.3% / 0.1% |
| Self-made FP8 v3 (concurrency 1 / 4) | 0.1% / 0.1% |
| Self-made INT4 (concurrency 1 / 4) | 0.1% / 0.6% |

A within-session range as small as 0.1%, yet a consistent 6–7% departure from
the old values. **The old values are not "unlucky" — they simply do not
reproduce under the current configuration.**

**A methodology point this exposed:** a single run is unreliable, **even on the
same day.** Earlier that day, a single run of self-made FP8 v3 at concurrency 4
gave 246.66, while the 3-run mean was 257.33 — a 4.3% deviation, far outside
its own 0.1% within-session range. The first round of a session also tends to
read low (third-party FP8 at concurrency 1: 71.5 on the first round vs 72.2 and
72.4 afterwards), which looks like a warmup effect.

## How the relative relationships moved

| Relationship | 2026-09-17 | 2026-09-22 (3-run means) |
|---|---:|---:|
| Self-made INT4 ÷ third-party FP8 (concurrency 1) | 1.53× | 1.43× |
| Self-made INT4 ÷ third-party FP8 (concurrency 4) | 1.44× | 1.30× |
| Self-made FP8 v3 ÷ third-party FP8 (concurrency 1) | 1.10× | 1.01× |
| Self-made FP8 v3 ÷ third-party FP8 (concurrency 4) | 1.09× | **1.00×** |

- INT4's advantage narrowed from about +52.6% / +43.7% to **+43.0% / +30.0%**,
  stable in direction and magnitude
- "Self-made FP8 v3 is slightly faster than third-party FP8" **has been
  retracted.** Two independent rounds now agree: **the two are
  throughput-equivalent**, so the selection must rest on quality alone

**Conclusions unaffected:** size reduction, the 200-question agreement rates,
memory-budget arithmetic, and the reasoning behind parameter choices — none of
these are throughput measurements, and none move between batches.

The full investigation, the raw GPU state records, and every script are in
[`wsl2-runner-verification.md`](wsl2-runner-verification.md).
