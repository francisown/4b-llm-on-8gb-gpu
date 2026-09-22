#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="/root/.venvs/ai-inference-week1"
MODEL_DIR="/mnt/e/Desktop/qwen3.5/model/qwen3.5-4b-fp8"

cd "$PROJECT_DIR"
source "$VENV_DIR/bin/activate"

exec env \
  VLLM_USE_V2_MODEL_RUNNER=0 \
  VLLM_USE_FLASHINFER_SAMPLER=0 \
  HF_HUB_OFFLINE=1 \
  TRANSFORMERS_OFFLINE=1 \
  vllm serve "$MODEL_DIR" \
    --served-model-name "Qwen3.5-4B-FP8" \
    --host 0.0.0.0 \
    --port 8000 \
    --language-model-only \
    --skip-mm-profiling \
    --enable-prefix-caching \
    --enable-chunked-prefill \
    --max-model-len 2048 \
    --max-num-seqs 16 \
    --gpu-memory-utilization 0.80
