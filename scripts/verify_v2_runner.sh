#!/usr/bin/env bash
# 一键完成 A/B 两个 runner 的对照实验：
#   A · VLLM_USE_V2_MODEL_RUNNER=0        （你现在的配置，V1 runner）
#   B · VLLM_WSL2_ENABLE_PIN_MEMORY=1     （新方案，期望走 V2 runner）
#
# 每个 case 会：启动服务 -> 等健康 -> 抓启动日志里的 runner 行 -> 压测 c1/c4
#              -> 停服务。最后打印对照结论。
#
# 注意：这个脚本会独占 GPU 并占用 8000 端口，全程约 10-20 分钟。
#       跑之前请确认没有别的 vLLM 实例在运行。
#
# 用法：
#   bash scripts/verify_v2_runner.sh            # 跑 A 和 B
#   bash scripts/verify_v2_runner.sh A          # 只跑 A
#   bash scripts/verify_v2_runner.sh B          # 只跑 B
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-/root/.venvs/ai-inference-week1}"
MODEL_DIR="${MODEL_DIR:-/mnt/e/Desktop/qwen3.5/model/qwen3.5-4b-int4-awq-self-v1}"
SERVED_NAME="${SERVED_NAME:-Qwen3.5-4B-INT4-AWQ}"
BASE_URL="http://127.0.0.1:8000"
RESULTS_DIR="$PROJECT_DIR/benchmark/results"
LOG_DIR="$RESULTS_DIR/runner-verify"
WAIT_SECONDS=300

WHICH="${1:-AB}"

cd "$PROJECT_DIR" || { echo "错误：找不到 $PROJECT_DIR"; exit 1; }
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate" || { echo "错误：无法激活 venv $VENV_DIR"; exit 1; }
mkdir -p "$LOG_DIR"

CURRENT_PGID=""
cleanup() {
  if [ -n "$CURRENT_PGID" ] && kill -0 "$CURRENT_PGID" 2>/dev/null; then
    echo "正在停止服务（进程组 $CURRENT_PGID）..."
    kill -TERM -- "-$CURRENT_PGID" 2>/dev/null
    for _ in $(seq 1 20); do
      kill -0 "$CURRENT_PGID" 2>/dev/null || break
      sleep 1
    done
    kill -KILL -- "-$CURRENT_PGID" 2>/dev/null
  fi
  CURRENT_PGID=""
}
trap 'cleanup; echo; echo "已中断。"' INT TERM

if curl -fsS "$BASE_URL/health" >/dev/null 2>&1; then
  echo "错误：$BASE_URL 已有服务在运行。请先停掉它（例如 pkill -f 'vllm serve'），再跑这个脚本。"
  exit 1
fi

run_case() {
  local label="$1"; shift
  local log="$LOG_DIR/${label}-server.log"
  local ready=0

  echo
  echo "=================================================================="
  echo "  开始 case $label"
  echo "  环境变量：$*"
  echo "  日志：$log"
  echo "=================================================================="

  : > "$log"
  setsid nohup env "$@" \
      VLLM_USE_FLASHINFER_SAMPLER=0 \
      HF_HUB_OFFLINE=1 \
      TRANSFORMERS_OFFLINE=1 \
      vllm serve "$MODEL_DIR" \
        --served-model-name "$SERVED_NAME" \
        --host 127.0.0.1 --port 8000 \
        --language-model-only --skip-mm-profiling \
        --enable-prefix-caching --enable-chunked-prefill \
        --max-model-len 2048 --max-num-seqs 16 --gpu-memory-utilization 0.80 \
      >> "$log" 2>&1 &
  CURRENT_PGID=$!

  echo "等待服务就绪（最多 ${WAIT_SECONDS}s）..."
  for _ in $(seq 1 $((WAIT_SECONDS / 2))); do
    if curl -fsS "$BASE_URL/health" >/dev/null 2>&1; then
      ready=1
      break
    fi
    if ! kill -0 "$CURRENT_PGID" 2>/dev/null; then
      echo "服务进程已退出，不再等待。请查看日志：$log"
      break
    fi
    sleep 2
  done

  if [ "$ready" -ne 1 ]; then
    echo ">>> case $label：服务未能就绪。关键日志如下："
    grep -iE "error|traceback|RuntimeError|UVA|pinned|model runner|not available" "$log" | tail -25
    cleanup
    return 1
  fi

  echo "服务已就绪。"
  echo
  echo "--- 启动日志中与 runner / pinned memory 相关的行 ---"
  grep -iE "model runner|pinned|UVA|pin memory|MRV2|V1 model|V2 model" "$log" | head -20 || echo "（未匹配到相关行）"

  for concurrency in 1 4; do
    local bench_label="${label}-c${concurrency}"
    echo
    echo "--- 压测 ${bench_label}（并发 ${concurrency}，16 请求，256in/128out）---"
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
      --save-result --save-detailed --disable-tqdm \
      --label "$bench_label" \
      --request-id-prefix "${bench_label}-" \
      --result-dir "$RESULTS_DIR" \
      --result-filename "${bench_label}.json" 2>&1 | tail -20
  done

  echo
  echo "--- case $label 期间 GPU 显存快照 ---"
  nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader 2>/dev/null || echo "（nvidia-smi 不可用）"

  cleanup
  echo "case $label 完成，服务已停止。"
  return 0
}

case "$WHICH" in
  A|a) run_case v1runner VLLM_USE_V2_MODEL_RUNNER=0 ;;
  B|b) run_case v2runner VLLM_WSL2_ENABLE_PIN_MEMORY=1 ;;
  AB|ab)
    run_case v1runner VLLM_USE_V2_MODEL_RUNNER=0
    sleep 5
    run_case v2runner VLLM_WSL2_ENABLE_PIN_MEMORY=1
    ;;
  *) echo "用法: bash scripts/verify_v2_runner.sh [A|B|AB]"; exit 1 ;;
esac

echo
echo "=================================================================="
echo "  对照结论"
echo "=================================================================="
python - <<'PY'
import json, os
base = "/mnt/e/AI-Inference-Lab/benchmark/results"
rows = []
for label, tag in (("v1runner", "A 现状 V1 runner"), ("v2runner", "B 新方案 V2+pinned")):
    for c in (1, 4):
        p = os.path.join(base, f"{label}-c{c}.json")
        if not os.path.exists(p):
            rows.append((tag, c, None, None, None))
            continue
        with open(p) as f:
            d = json.load(f)
        def pick(*names):
            for n in names:
                if n in d and isinstance(d[n], (int, float)):
                    return d[n]
            return None
        rows.append((
            tag, c,
            pick("output_throughput"),
            pick("p50_ttft_ms", "median_ttft_ms"),
            pick("p50_tpot_ms", "median_tpot_ms"),
        ))

print(f"{'配置':<22}{'并发':>4}{'输出吞吐 tok/s':>18}{'TTFT P50 ms':>14}{'TPOT P50 ms':>14}")
for tag, c, tp, ttft, tpot in rows:
    fmt = lambda v: "-" if v is None else f"{v:.2f}"
    print(f"{tag:<22}{c:>4}{fmt(tp):>18}{fmt(ttft):>14}{fmt(tpot):>14}")

d = {tag: {} for tag, *_ in rows}
for tag, c, tp, *_ in rows:
    d[tag][c] = tp
a, b = "A 现状 V1 runner", "B 新方案 V2+pinned"
for c in (1, 4):
    if d.get(a, {}).get(c) and d.get(b, {}).get(c):
        delta = (d[b][c] - d[a][c]) / d[a][c] * 100
        print(f"并发 {c}：B 相对 A {delta:+.1f}%")
print()
print("历史参考（V1 runner，INT4-AWQ compiled）：并发 1 = 109.12 tok/s，并发 4 = 359.71 tok/s")
PY
echo
echo "服务端日志已保存到：$LOG_DIR"
echo "请把上面的「对照结论」表格连同两个 server.log 的 runner 相关行贴回对话。"
