#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="/root/.venvs/ai-inference-week1"
MODEL_DIR="/mnt/e/AI-Inference-Lab/models/Qwen3-0.6B"

cd "$PROJECT_DIR"
source "$VENV_DIR/bin/activate"

exec env \
  VLLM_USE_V2_MODEL_RUNNER=0 \
  VLLM_USE_FLASHINFER_SAMPLER=0 \
  HF_HUB_OFFLINE=1 \
  TRANSFORMERS_OFFLINE=1 \
  vllm serve "$MODEL_DIR" \
    --served-model-name "Qwen/Qwen3-0.6B" \
    --host 0.0.0.0 \
    --port 8000 \
    --max-model-len 4096 \
    --gpu-memory-utilization 0.70
