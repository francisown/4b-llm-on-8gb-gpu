#!/usr/bin/env bash
# 三个量化模型的重复对照：每个模型连跑 N 轮 c1/c4，给出均值与离散度。
#
# 为什么需要它：
#   2026-09-22 的同批重测出现了非均匀变化——三个量化模型的吞吐变化方向不一致：
#     第三方 FP8   +1.1% / +1.6%
#     自制 FP8 v3  -6.8% / -9.6%
#     自制 INT4    -5.8% / -8.3%
#   这不像统一的"环境漂移"，而且导致一个重要相对结论翻转：
#   旧数据里自制 FP8 v3 在并发 4 比第三方 FP8 快约 9%，新数据里变成慢约 3%。
#
#   另外当天记录的 GPU 状态显示没有降频（throttle_reasons = 0x0、温度 49-63C、
#   功耗远低于 145W 上限、SM 时钟甚至从 2535 升到 2752 MHz），
#   所以"热降频导致漂移"这个解释不被数据支持。
#
#   在把任何相对结论写进对外材料之前，必须先确认这个差异是真实的还是单次波动。
#   本脚本用重复测量来回答它。
#
# 用法：
#   bash scripts/repeat_bench_quant.sh        # 默认 3 轮
#   bash scripts/repeat_bench_quant.sh 5      # 5 轮
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-/root/.venvs/ai-inference-week1}"
BASE_URL="http://127.0.0.1:8000"
RESULTS_DIR="$PROJECT_DIR/benchmark/results"
LOG_DIR="$RESULTS_DIR/rebaseline"
WAIT_SECONDS=300
ROUNDS="${1:-3}"
PREFIX="rbq"

MODELS=(
  "third-fp8|/mnt/e/Desktop/qwen3.5/model/qwen3.5-4b-fp8|Qwen3.5-4B-FP8"
  "self-fp8v3|/mnt/e/Desktop/qwen3.5/model/qwen3.5-4b-fp8-self-v3|Qwen3.5-4B-FP8-self-v3"
  "int4awq|/mnt/e/Desktop/qwen3.5/model/qwen3.5-4b-int4-awq-self-v1|Qwen3.5-4B-INT4-AWQ"
)

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
  echo "错误：$BASE_URL 已有服务在运行。请先停掉它。"
  exit 1
fi

run_model() {
  local tag="$1" model="$2" name="$3"
  local log="$LOG_DIR/${PREFIX}-${tag}-server.log"

  echo
  echo "=================================================================="
  echo "  模型 $tag（$name）"
  echo "  每轮 c1 + c4，共 $ROUNDS 轮"
  echo "=================================================================="

  : > "$log"
  setsid nohup env VLLM_USE_V2_MODEL_RUNNER=0 \
      VLLM_USE_FLASHINFER_SAMPLER=0 \
      HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
      vllm serve "$model" \
        --served-model-name "$name" \
        --host 127.0.0.1 --port 8000 \
        --language-model-only --skip-mm-profiling \
        --enable-prefix-caching --enable-chunked-prefill \
        --max-model-len 2048 --max-num-seqs 16 --gpu-memory-utilization 0.80 \
      >> "$log" 2>&1 &
  CURRENT_PGID=$!

  local ready=0
  for _ in $(seq 1 $((WAIT_SECONDS / 2))); do
    if curl -fsS "$BASE_URL/health" >/dev/null 2>&1; then ready=1; break; fi
    kill -0 "$CURRENT_PGID" 2>/dev/null || break
    sleep 2
  done
  if [ "$ready" -ne 1 ]; then
    echo ">>> $tag 服务未就绪，跳过。关键日志："
    grep -iE "error|traceback|RuntimeError" "$log" | tail -15
    cleanup
    return 1
  fi
  echo "服务已就绪。"

  for r in $(seq 1 "$ROUNDS"); do
    for c in 1 4; do
      local label="${PREFIX}-${tag}-r${r}-c${c}"
      echo "  --- $label ---"
      HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 vllm bench serve \
        --backend openai --base-url "$BASE_URL" --endpoint /v1/completions \
        --model "$model" --served-model-name "$name" --tokenizer "$model" \
        --dataset-name random \
        --random-input-len 256 --random-output-len 128 --random-range-ratio 0 \
        --num-prompts "${NUM_PROMPTS:-64}" --num-warmups 2 --max-concurrency "$c" \
        --request-rate inf --ignore-eos --temperature 0 \
        --metric-percentiles 50,95,99 --percentile-metrics ttft,tpot,itl,e2el \
        --save-result --disable-tqdm \
        --label "$label" --request-id-prefix "${label}-" \
        --result-dir "$RESULTS_DIR" --result-filename "${label}.json" 2>&1 | tail -3
    done
  done

  local line
  line="$(nvidia-smi --query-gpu=clocks.sm,power.draw,temperature.gpu,clocks_throttle_reasons.active --format=csv,noheader,nounits 2>/dev/null | head -1)"
  echo "  收尾 GPU 状态：$line"
  cleanup
  sleep 5
}

for entry in "${MODELS[@]}"; do
  IFS='|' read -r tag model name <<< "$entry"
  run_model "$tag" "$model" "$name"
done

echo
echo "=================================================================="
echo "  三个量化模型重复对照（每配置 $ROUNDS 轮）"
echo "=================================================================="
XREPS="$ROUNDS" python - <<'PY'
import json, os, statistics as st

base = "/mnt/e/AI-Inference-Lab/benchmark/results"
reps = int(os.environ.get("XREPS", "3"))

MODELS = [
    ("第三方 FP8",  "third-fp8",  {1: 71.53, 4: 250.26}),
    ("自制 FP8 v3", "self-fp8v3", {1: 78.44, 4: 272.84}),
    ("自制 INT4",   "int4awq",    {1: 109.12, 4: 359.71}),
]
OLD_0922 = {
    ("第三方 FP8", 1): 72.32,  ("第三方 FP8", 4): 254.18,
    ("自制 FP8 v3", 1): 73.12, ("自制 FP8 v3", 4): 246.66,
    ("自制 INT4", 1): 102.75,  ("自制 INT4", 4): 329.74,
}


def samples(tag, c):
    out = []
    for r in range(1, reps + 1):
        p = os.path.join(base, f"rbq-{tag}-r{r}-c{c}.json")
        if not os.path.exists(p):
            continue
        with open(p) as f:
            d = json.load(f)
        v = d.get("output_throughput")
        if isinstance(v, (int, float)):
            out.append(v)
    return out


means = {}
print(f"{'模型':<14}{'并发':>4}{'样本':>34}{'均值':>10}{'极差%':>8}{'标准差':>9}{'vs 09-17':>11}{'vs 09-22':>11}")
print("-" * 104)
for name, tag, old in MODELS:
    for c in (1, 4):
        vals = samples(tag, c)
        if not vals:
            print(f"{name:<14}{c:>4}{'  （无样本）':>34}")
            continue
        mean = st.mean(vals)
        spread = (max(vals) - min(vals)) / mean * 100 if mean else 0
        sd = st.stdev(vals) if len(vals) > 1 else 0
        versus_old = (mean - old[c]) / old[c] * 100
        o22 = OLD_0922.get((name, c))
        versus_22 = (mean - o22) / o22 * 100 if o22 else float("nan")
        means[(name, c)] = mean
        print(f"{name:<14}{c:>4}{'  '.join(f'{v:.1f}' for v in vals):>34}"
              f"{mean:>10.2f}{spread:>8.1f}{sd:>9.2f}{versus_old:>10.1f}%{versus_22:>10.1f}%")

print()
print("跨模型相对关系（用本轮均值）")
print("-" * 104)
for c in (1, 4):
    t = means.get(("第三方 FP8", c))
    s = means.get(("自制 FP8 v3", c))
    i = means.get(("自制 INT4", c))
    if not (t and s and i):
        continue
    print(f"并发 {c}：第三方 FP8 = {t:.2f} | 自制 FP8 v3 = {s:.2f} （相对第三方 {(s - t) / t * 100:+.1f}%）"
          f" | 自制 INT4 = {i:.2f}（相对第三方 {(i - t) / t * 100:+.1f}%）")

print()
print("判读方法：")
print("  1. 先看各配置的极差与标准差。若极差 < 3%，说明本轮测量稳定，均值可用。")
print("  2. 再看「自制 FP8 v3 相对第三方 FP8」这一行。")
print("     - 若仍为负值且超出离散度 → 旧结论「自制 FP8 v3 吞吐略高于第三方 FP8」应彻底删除")
print("     - 若在正负之间摆动 → 两者吞吐等价，选型只能依据质量一致率，不能依据吞吐")
print("  3. 自制 INT4 相对第三方的优势（旧数据约 +40%）若依然稳固，则不受本次波动影响。")
PY
echo
echo "逐轮 JSON 在 $RESULTS_DIR（前缀 ${PREFIX}-*）"
echo "请把上面两张表贴回对话。"
