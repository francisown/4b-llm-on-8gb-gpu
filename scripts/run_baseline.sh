#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="/root/.venvs/ai-inference-week1"
MODEL_DIR="/mnt/e/AI-Inference-Lab/models/Qwen3-0.6B"
MODEL_NAME="Qwen/Qwen3-0.6B"
BASE_URL="http://127.0.0.1:8000"
RESULT_DIR="$PROJECT_DIR/benchmark/results"

cd "$PROJECT_DIR"
source "$VENV_DIR/bin/activate"

if ! curl -fsS "$BASE_URL/health" >/dev/null; then
  echo "错误：vLLM 服务没有运行。请先在另一个终端执行："
  echo "  $PROJECT_DIR/scripts/start_server.sh"
  exit 1
fi

mkdir -p "$RESULT_DIR"

for concurrency in 1 4 16 64; do
  echo
  echo "===== 正在测试并发 $concurrency ====="

  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 vllm bench serve \
    --backend openai \
    --base-url "$BASE_URL" \
    --endpoint /v1/completions \
    --model "$MODEL_DIR" \
    --served-model-name "$MODEL_NAME" \
    --tokenizer "$MODEL_DIR" \
    --dataset-name random \
    --random-input-len 256 \
    --random-output-len 128 \
    --random-range-ratio 0 \
    --num-prompts 64 \
    --num-warmups 2 \
    --max-concurrency "$concurrency" \
    --request-rate inf \
    --ignore-eos \
    --temperature 0 \
    --metric-percentiles 50,95,99 \
    --percentile-metrics ttft,tpot,itl,e2el \
    --save-result \
    --save-detailed \
    --disable-tqdm \
    --label "baseline-c$concurrency" \
    --request-id-prefix "baseline-c$concurrency-" \
    --result-dir "$RESULT_DIR" \
    --result-filename "baseline-c$concurrency.json"
done

echo
echo "基线压测完成，原始结果保存在：$RESULT_DIR"
