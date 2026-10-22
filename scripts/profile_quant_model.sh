#!/usr/bin/env bash
# Capture an Nsight Systems trace for a quantization comparison run.
#
# This does not replace the throughput benchmark: it exists to answer *why*
# INT4-AWQ is faster than FP8 on this GPU. Look at kernel time, memory
# throughput, and whether the AWQ dequant kernels are on the critical path.
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
MODEL="${MODEL:?set MODEL to the served model name}"
MODEL_PATH="${MODEL_PATH:?set MODEL_PATH to the tokenizer/model directory}"
OUT="${OUT:-$PROJECT_DIR/benchmark/results/profiles/quant-$(date +%Y%m%d-%H%M%S)}"

if ! command -v nsys >/dev/null 2>&1; then
  echo "nsys not found. Install Nsight Systems and retry." >&2
  exit 1
fi

mkdir -p "$(dirname "$OUT")"

nsys profile \
  --trace=cuda,nvtx,osrt \
  --sample=none \
  --cpuctxsw=none \
  --stats=true \
  --force-overwrite=true \
  -o "$OUT" \
  vllm bench serve \
    --backend openai \
    --base-url "$BASE_URL" \
    --endpoint /v1/completions \
    --model "$MODEL_PATH" \
    --served-model-name "$MODEL" \
    --tokenizer "$MODEL_PATH" \
    --dataset-name random \
    --random-input-len 256 \
    --random-output-len 128 \
    --random-range-ratio 0 \
    --num-prompts "${NUM_PROMPTS:-64}" \
    --num-warmups 2 \
    --max-concurrency "${CONCURRENCY:-4}" \
    --request-rate inf \
    --ignore-eos \
    --temperature 0

echo "Trace written to ${OUT}.nsys-rep"
