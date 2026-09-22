#!/usr/bin/env bash
# 重复压测：同一配置连跑 N 轮，用来判断"单次结果是否可信"。
#
# 背景：2026-09-22 的 A/B 对照里，V1 runner 实测 c1=102.35 / c4=332.74 tok/s，
# 而 2026-09-17 记录的历史值是 c1=109.12 / c4=359.71。两者相差约 6-7%，
# 参数（num_prompts=16、并发 1/4、256in/128out）却完全一致。
# 这台机器此前出现过 per-token 延迟双峰，所以单跑一遍不能作为结论。
#
# 本脚本只起一次服务，然后在同一进程内连跑 N 轮 c1/c4，把启动开销排除在外，
# 单独暴露"测量噪声"有多大。
#
# 用法：
#   bash scripts/repeat_bench_v1.sh          # 默认 3 轮
#   bash scripts/repeat_bench_v1.sh 5        # 5 轮
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-/root/.venvs/ai-inference-week1}"
MODEL_DIR="${MODEL_DIR:-/mnt/e/Desktop/qwen3.5/model/qwen3.5-4b-int4-awq-self-v1}"
SERVED_NAME="${SERVED_NAME:-Qwen3.5-4B-INT4-AWQ}"
BASE_URL="http://127.0.0.1:8000"
RESULTS_DIR="$PROJECT_DIR/benchmark/results"
LOG_DIR="$RESULTS_DIR/runner-verify"
REPS="${1:-3}"
WAIT_SECONDS=300
LABEL_PREFIX="${LABEL_PREFIX:-repeatA}"

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
  echo "错误：$BASE_URL 已有服务在运行。请先停掉它，再跑这个脚本。"
  exit 1
fi

log="$LOG_DIR/${LABEL_PREFIX}-server.log"
echo "启动服务（V1 runner，与你当前配置一致）..."
: > "$log"
setsid nohup env VLLM_USE_V2_MODEL_RUNNER=0 \
    VLLM_USE_FLASHINFER_SAMPLER=0 \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    vllm serve "$MODEL_DIR" \
      --served-model-name "$SERVED_NAME" \
      --host 127.0.0.1 --port 8000 \
      --language-model-only --skip-mm-profiling \
      --enable-prefix-caching --enable-chunked-prefill \
      --max-model-len 2048 --max-num-seqs 16 --gpu-memory-utilization 0.80 \
    >> "$log" 2>&1 &
CURRENT_PGID=$!

echo "等待服务就绪（最多 ${WAIT_SECONDS}s）..."
ready=0
for _ in $(seq 1 $((WAIT_SECONDS / 2))); do
  if curl -fsS "$BASE_URL/health" >/dev/null 2>&1; then ready=1; break; fi
  kill -0 "$CURRENT_PGID" 2>/dev/null || { echo "服务已退出，见日志 $log"; break; }
  sleep 2
done
if [ "$ready" -ne 1 ]; then
  echo "服务未能就绪，退出。关键日志："
  grep -iE "error|traceback|RuntimeError" "$log" | tail -20
  cleanup
  exit 1
fi
echo "服务已就绪，开始 ${REPS} 轮重复压测。"
echo

for rep in $(seq 1 "$REPS"); do
  for concurrency in 1 4; do
    label="${LABEL_PREFIX}-r${rep}-c${concurrency}"
    echo "===== 第 ${rep} 轮 / 并发 ${concurrency} ====="
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 vllm bench serve \
      --backend openai --base-url "$BASE_URL" --endpoint /v1/completions \
      --model "$MODEL_DIR" --served-model-name "$SERVED_NAME" --tokenizer "$MODEL_DIR" \
      --dataset-name random \
      --random-input-len 256 --random-output-len 128 --random-range-ratio 0 \
      --num-prompts 16 --max-concurrency "$concurrency" \
      --request-rate inf --ignore-eos --temperature 0 \
      --metric-percentiles 50,95,99 --percentile-metrics ttft,tpot,itl,e2el \
      --save-result --disable-tqdm \
      --label "$label" --request-id-prefix "${label}-" \
      --result-dir "$RESULTS_DIR" --result-filename "${label}.json" 2>&1 | tail -4
    echo
  done
done

cleanup
echo "服务已停止。"

echo
echo "=================================================================="
echo "  重复性结论（同一进程内的 $REPS 轮）"
echo "=================================================================="
XLABEL="$LABEL_PREFIX" XREPS="$REPS" python - <<'PY'
import json, os, statistics as st

base = "/mnt/e/AI-Inference-Lab/benchmark/results"
prefix = os.environ.get("XLABEL", "repeatA")
reps = int(os.environ.get("XREPS", "3"))

HIST = {1: 109.12, 4: 359.71}
FEB22 = {1: 102.35, 4: 332.74}

for c in (1, 4):
    vals = []
    for r in range(1, reps + 1):
        p = os.path.join(base, f"{prefix}-r{r}-c{c}.json")
        if not os.path.exists(p):
            continue
        with open(p) as f:
            d = json.load(f)
        v = d.get("output_throughput")
        if isinstance(v, (int, float)):
            vals.append(v)
    if not vals:
        print(f"并发 {c}：没有可用样本")
        continue
    mean = st.mean(vals)
    lo, hi = min(vals), max(vals)
    spread = (hi - lo) / mean * 100 if mean else 0
    print(f"并发 {c}")
    print(f"  样本         : {', '.join(f'{v:.2f}' for v in vals)}")
    print(f"  均值         : {mean:.2f} tok/s")
    print(f"  极差         : {hi - lo:.2f} tok/s（占均值 {spread:.1f}%）")
    if len(vals) > 1:
        print(f"  样本标准差   : {st.stdev(vals):.2f}")
    h = HIST.get(c, 0)
    print(f"  对比历史 {h} : {(mean - h) / h * 100:+.1f}%")
    print(f"  对比 09-22 {FEB22.get(c, 0)}: {(mean - FEB22.get(c, 0)) / FEB22.get(c, 0) * 100:+.1f}%")
    print()
print("判读方法：")
print("  若极差很小（<2%）且均值稳定偏离历史值 → 历史数字当前不可复现，需要重定基线")
print("  若样本在两组值之间跳动（双峰） → 单次结果都不可用，必须报区间")
PY
echo
echo "逐轮 JSON 已保存到 $RESULTS_DIR（前缀 ${LABEL_PREFIX}-r*）"
