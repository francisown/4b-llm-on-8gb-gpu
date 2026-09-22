#!/usr/bin/env bash
# 对当前正在运行的服务做一次固定条件压测，产出可直接与历史结果对比的 JSON。
#
# 固定条件与 benchmark/eval/README.md 中的量化对比保持一致：
#   256 input / 128 output、16 个请求、temperature=0、并发 1 与 4
#
# 用法：
#   bash scripts/bench_qwen35_int4.sh <label 前缀>
# 例如：
#   bash scripts/bench_qwen35_int4.sh v1runner-int4     # 现状基线
#   bash scripts/bench_qwen35_int4.sh v2runner-int4     # V2 runner 方案
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-/root/.venvs/ai-inference-week1}"
MODEL_DIR="${MODEL_DIR:-/mnt/e/Desktop/qwen3.5/model/qwen3.5-4b-int4-awq-self-v1}"
SERVED_NAME="${SERVED_NAME:-Qwen3.5-4B-INT4-AWQ}"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
RESULT_DIR="$PROJECT_DIR/benchmark/results"
LABEL_PREFIX="${1:?用法: bash scripts/bench_qwen35_int4.sh <label 前缀>}"

cd "$PROJECT_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

if ! curl -fsS "$BASE_URL/health" >/dev/null; then
  echo "错误：$BASE_URL/health 不可达，vLLM 服务未运行。请先在另一个终端启动服务。"
  exit 1
fi

echo "正在读取服务端实际运行的 model runner 版本 ..."
curl -fsS "$BASE_URL/health" >/dev/null && echo "健康检查：通过"
echo "提示：model runner 版本请以服务端启动日志里的 Model Runner V1 / V2 字样为准，本脚本无法从 API 读到。"

mkdir -p "$RESULT_DIR"

for concurrency in 1 4; do
  label="${LABEL_PREFIX}-c${concurrency}"
  echo
  echo "===== ${label}（并发 ${concurrency}）====="

  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 vllm bench serve \
    --backend openai \
    --base-url "$BASE_URL" \
    --endpoint /v1/completions \
    --model "$MODEL_DIR" \
    --served-model-name "$SERVED_NAME" \
    --tokenizer "$MODEL_DIR" \
    --dataset-name random \
    --random-input-len 256 \
    --random-output-len 128 \
    --random-range-ratio 0 \
    --num-prompts 16 \
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
    --label "$label" \
    --request-id-prefix "${label}-" \
    --result-dir "$RESULT_DIR" \
    --result-filename "${label}.json"
done

echo
echo "压测完成，结果已保存到：$RESULT_DIR"
echo "对照参考（历史值，INT4-AWQ compiled）：并发 1 = 109.12 tok/s，并发 4 = 359.71 tok/s"
