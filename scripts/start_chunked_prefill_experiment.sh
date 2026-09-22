#!/usr/bin/env bash
set -Eeuo pipefail

MODE="${1:-on}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="/root/.venvs/ai-inference-week1"
MODEL_DIR="/mnt/e/Desktop/qwen3.5/model/qwen3.5-4b-fp8"
PORT="${VLLM_EXPERIMENT_PORT:-18001}"

case "$MODE" in
  on)
    CHUNKED_ARGS=(--enable-prefix-caching --enable-chunked-prefill --max-num-batched-tokens 1024)
    ;;
  off)
    CHUNKED_ARGS=(--no-enable-prefix-caching --no-enable-chunked-prefill --max-num-batched-tokens 2048)
    ;;
  *)
    echo "Usage: $0 on|off" >&2
    exit 2
    ;;
esac

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
    --port "$PORT" \
    --language-model-only \
    --skip-mm-profiling \
    --max-model-len 2048 \
    --max-num-seqs 16 \
    --gpu-memory-utilization 0.80 \
    "${CHUNKED_ARGS[@]}"
