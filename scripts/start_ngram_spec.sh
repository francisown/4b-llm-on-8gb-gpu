#!/usr/bin/env bash
set -euo pipefail

cd /mnt/e/AI-Inference-Lab
source /root/.venvs/ai-inference-bin/activate

# This WSL environment has the CUDA runtime but no nvcc. Without this setting,
# FlashInfer may try to JIT-compile its sampler and fail during vLLM warmup.
export VLLM_USE_FLASHINFER_SAMPLER=0

exec vllm serve /mnt/e/Desktop/qwen3.5/model/qwen3.5-4b-int4-awq-self-v1 \
  --served-model-name Qwen3.5-4B-INT4-AWQ-self \
  --host 0.0.0.0 \
  --port 8000 \
  --language-model-only \
  --max-model-len 1024 \
  --max-num-batched-tokens 512 \
  --max-num-seqs 4 \
  --gpu-memory-utilization 0.85 \
  --enable-prefix-caching \
  --speculative-config.method ngram \
  --speculative-config.num-speculative-tokens 5 \
  --speculative-config.prompt-lookup-min 2 \
  --speculative-config.prompt-lookup-max 5
