#!/usr/bin/env bash
# 重定性能基线：在一次会话内把对外要用到的全部性能数字重测一遍。
#
# 为什么需要：
#   2026-09-17 记录的数字与 2026-09-22 用完全相同的参数复测，相差 6-7%
#   （并发 1：109.12 -> 102.22；并发 4：359.71 -> 332.29）。
#   09-22 的重复压测显示同会话内极差只有 0.6%-1.2%、标准差 <1，说明当次测量本身很精确，
#   偏差来自跨会话的环境漂移（GPU 时钟/温度/功耗状态等），而不是测量噪声。
#
#   因此对外数字必须在同一次会话内产出，否则彼此不可比。
#
# 覆盖范围（与对外材料里用到的数字一一对应）：
#   Qwen3.5-4B 第三方 FP8      并发 1/4   —— 交付模型，量化三向对比
#   Qwen3.5-4B 自制 FP8 v3     并发 1/4   —— 交付模型
#   Qwen3.5-4B 自制 INT4-AWQ   并发 1/4   —— 交付模型
#   Qwen3-0.6B 并发 1/4/16/64            —— 引擎批处理基线（测试负载，非交付模型）
#
# 关于最后一个：它测的是引擎而不是模型，用轻量负载把"连续批处理如何把并发换成吞吐"
# 单独逼出来。它不说明交付模型的性能，但因为 README 里引用了这条曲线，也需要同批重测
# 才能保证全仓库的数字彼此可比。只关心交付模型时用 `qwen35` 跳过它即可。
#
# 顺带记录每次压测前后的 GPU 状态（时钟/功耗/温度/降频原因），
# 让以后出现漂移时有据可查，而不用再靠猜。
#
# 预计 15-25 分钟，会独占 GPU 与 8000 端口。
#
# 用法：
#   bash scripts/rebuild_baseline.sh           # 跑全部
#   bash scripts/rebuild_baseline.sh qwen3     # 只跑 Qwen3-0.6B 并发 sweep
#   bash scripts/rebuild_baseline.sh qwen35    # 只跑三个 Qwen3.5-4B 量化模型
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-/root/.venvs/ai-inference-week1}"
BASE_URL="http://127.0.0.1:8000"
RESULTS_DIR="$PROJECT_DIR/benchmark/results"
LOG_DIR="$RESULTS_DIR/rebaseline"
GPU_CSV="$LOG_DIR/gpu-state.csv"
WAIT_SECONDS=300
WHICH="${1:-ALL}"

SMALL_MODEL="/mnt/e/AI-Inference-Lab/models/Qwen3-0.6B"
SMALL_NAME="Qwen/Qwen3-0.6B"
PREFIX="rb"

cd "$PROJECT_DIR" || { echo "错误：找不到 $PROJECT_DIR"; exit 1; }
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate" || { echo "错误：无法激活 venv $VENV_DIR"; exit 1; }
mkdir -p "$LOG_DIR"

if [ ! -f "$GPU_CSV" ]; then
  echo "stage,tag,clocks_sm_mhz,clocks_mem_mhz,power_w,power_limit_w,temp_c,util_pct,mem_used_mib,pstate,throttle_reasons" > "$GPU_CSV"
fi

CURRENT_PGID=""
SERVER_LOG=""

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

gpu_state() {
  # $1 = stage 描述, $2 = tag
  local line
  line="$(nvidia-smi --query-gpu=clocks.sm,clocks.mem,power.draw,power.limit,temperature.gpu,utilization.gpu,memory.used,pstate,clocks_throttle_reasons.active --format=csv,noheader,nounits 2>/dev/null | head -1)"
  if [ -z "$line" ]; then
    echo "$1,$2,na,na,na,na,na,na,na,na,na" >> "$GPU_CSV"
    return
  fi
  echo "$1,$2,$line" >> "$GPU_CSV"
}

wait_ready() {
  local ready=0
  for _ in $(seq 1 $((WAIT_SECONDS / 2))); do
    if curl -fsS "$BASE_URL/health" >/dev/null 2>&1; then ready=1; break; fi
    kill -0 "$CURRENT_PGID" 2>/dev/null || break
    sleep 2
  done
  [ "$ready" -eq 1 ]
}

start_server() {
  # $1 = log 文件名, 之后为环境变量赋值
  local logname="$1"; shift
  SERVER_LOG="$LOG_DIR/$logname"
  : > "$SERVER_LOG"
  echo "启动服务 -> $SERVER_LOG"
  echo "  环境/参数：$*"
  setsid nohup env "$@" VLLM_USE_FLASHINFER_SAMPLER=0 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
      vllm serve "$LAUNCH_MODEL" --served-model-name "$LAUNCH_NAME" \
        --host 127.0.0.1 --port 8000 \
        "${LAUNCH_EXTRA[@]}" \
      >> "$SERVER_LOG" 2>&1 &
  CURRENT_PGID=$!
  if wait_ready; then
    echo "服务已就绪。"
    grep -iE "Using V[12] Model Runner" "$SERVER_LOG" | tail -2 || true
    gpu_state "idle_after_start" "$(basename "$logname" .log)"
    return 0
  fi
  echo ">>> 服务未就绪。关键日志："
  grep -iE "error|traceback|RuntimeError" "$SERVER_LOG" | tail -15
  cleanup
  return 1
}

bench() {
  # $1 = tag, $2 = concurrency, $3 = num_prompts
  local tag="$1" c="$2" n="$3"
  local label="${PREFIX}-${tag}-c${c}"
  echo "  --- $label (并发 $c, $n 请求) ---"
  gpu_state "before_bench" "$label"
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 vllm bench serve \
    --backend openai --base-url "$BASE_URL" --endpoint /v1/completions \
    --model "$BENCH_MODEL" --served-model-name "$BENCH_NAME" --tokenizer "$BENCH_MODEL" \
    --dataset-name random \
    --random-input-len 256 --random-output-len 128 --random-range-ratio 0 \
    --num-prompts "$n" --num-warmups 2 --max-concurrency "$c" \
    --request-rate inf --ignore-eos --temperature 0 \
    --metric-percentiles 50,95,99 --percentile-metrics ttft,tpot,itl,e2el \
    --save-result --save-detailed --disable-tqdm \
    --label "$label" --request-id-prefix "${label}-" \
    --result-dir "$RESULTS_DIR" --result-filename "${label}.json" 2>&1 | tail -3
  gpu_state "after_bench" "$label"
}

run_small() {
  echo
  echo "=================================================================="
  echo "  Qwen3-0.6B 并发 sweep（对应 README 的吞吐曲线）"
  echo "  注意：这是 Qwen3-0.6B，不是量化用的 Qwen3.5-4B"
  echo "=================================================================="
  LAUNCH_MODEL="$SMALL_MODEL"
  LAUNCH_NAME="$SMALL_NAME"
  LAUNCH_EXTRA=(--max-model-len 4096 --gpu-memory-utilization 0.70)
  BENCH_MODEL="$SMALL_MODEL"
  BENCH_NAME="$SMALL_NAME"
  start_server "qwen3-06b-server.log" VLLM_USE_V2_MODEL_RUNNER=0 || return 1
  for c in 1 4 16 64; do bench "qwen3-06b" "$c" 64; done
  cleanup
}

run_quant() {
  local tag="$1" model="$2" name="$3"
  echo
  echo "=================================================================="
  echo "  量化模型 $tag"
  echo "=================================================================="
  LAUNCH_MODEL="$model"
  LAUNCH_NAME="$name"
  LAUNCH_EXTRA=(--language-model-only --skip-mm-profiling
                --enable-prefix-caching --enable-chunked-prefill
                --max-model-len 2048 --max-num-seqs 16 --gpu-memory-utilization 0.80)
  BENCH_MODEL="$model"
  BENCH_NAME="$name"
  start_server "${tag}-server.log" VLLM_USE_V2_MODEL_RUNNER=0 || return 1
  for c in 1 4; do bench "$tag" "$c" 16; done
  cleanup
  sleep 5
}

if [ -n "${BASH_VERSINFO:-}" ]; then :; fi

case "$WHICH" in
  qwen3|06b|small) run_small ;;
  qwen35|quant)
    run_quant "qwen35-third-fp8"  "/mnt/e/Desktop/qwen3.5/model/qwen3.5-4b-fp8"        "Qwen3.5-4B-FP8"
    run_quant "qwen35-self-fp8v3" "/mnt/e/Desktop/qwen3.5/model/qwen3.5-4b-fp8-self-v3" "Qwen3.5-4B-FP8-self-v3"
    run_quant "qwen35-int4awq"    "/mnt/e/Desktop/qwen3.5/model/qwen3.5-4b-int4-awq-self-v1" "Qwen3.5-4B-INT4-AWQ"
    ;;
  ALL|all)
    run_small
    sleep 5
    run_quant "qwen35-third-fp8"  "/mnt/e/Desktop/qwen3.5/model/qwen3.5-4b-fp8"        "Qwen3.5-4B-FP8"
    run_quant "qwen35-self-fp8v3" "/mnt/e/Desktop/qwen3.5/model/qwen3.5-4b-fp8-self-v3" "Qwen3.5-4B-FP8-self-v3"
    run_quant "qwen35-int4awq"    "/mnt/e/Desktop/qwen3.5/model/qwen3.5-4b-int4-awq-self-v1" "Qwen3.5-4B-INT4-AWQ"
    ;;
  *) echo "用法: bash scripts/rebuild_baseline.sh [ALL|qwen3|qwen35]"; exit 1 ;;
esac

cleanup

echo
echo "=================================================================="
echo "  新旧基线对照"
echo "=================================================================="
python - <<'PY'
import json, os

base = "/mnt/e/AI-Inference-Lab/benchmark/results"

# (说明, 新 tag, 并发, 旧文件名)
PAIRS = [
    ("Qwen3-0.6B",    "rb-qwen3-06b",        1,  "baseline-c1.json"),
    ("Qwen3-0.6B",    "rb-qwen3-06b",        4,  "baseline-c4.json"),
    ("Qwen3-0.6B",    "rb-qwen3-06b",        16, "baseline-c16.json"),
    ("Qwen3-0.6B",    "rb-qwen3-06b",        64, "baseline-c64.json"),
    ("Qwen3.5-4B 第三方 FP8",  "rb-qwen35-third-fp8",  1,  "quant-third-compiled-c1.json"),
    ("Qwen3.5-4B 第三方 FP8",  "rb-qwen35-third-fp8",  4,  "quant-third-compiled-c4.json"),
    ("Qwen3.5-4B 自制 FP8 v3", "rb-qwen35-self-fp8v3", 1,  "quant-self-v3-compiled-c1.json"),
    ("Qwen3.5-4B 自制 FP8 v3", "rb-qwen35-self-fp8v3", 4,  "quant-self-v3-compiled-c4.json"),
    ("Qwen3.5-4B INT4-AWQ",    "rb-qwen35-int4awq",    1,  "qwen35-int4-awq-self-compiled-c1.json"),
    ("Qwen3.5-4B INT4-AWQ",    "rb-qwen35-int4awq",    4,  "qwen35-int4-awq-self-compiled-c4.json"),
]


def throughput(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        d = json.load(f)
    v = d.get("output_throughput")
    return v if isinstance(v, (int, float)) else None


print(f"{'模型':<16}{'并发':>4}{'旧值':>12}{'新值':>12}{'变化':>10}")
print("-" * 56)
changed = []
for name, tag, c, old in PAIRS:
    new_p = os.path.join(base, f"{tag}-c{c}.json")
    old_p = os.path.join(base, old)
    ov, nv = throughput(old_p), throughput(new_p)
    os_, ns = ("-" if ov is None else f"{ov:.2f}"), ("-" if nv is None else f"{nv:.2f}")
    delta = "-"
    if ov and nv:
        d = (nv - ov) / ov * 100
        delta = f"{d:+.1f}%"
        changed.append(d)
    print(f"{name:<16}{c:>4}{os_:>12}{ns:>12}{delta:>10}")

print()
if changed:
    print(f"平均变化：{sum(changed)/len(changed):+.1f}%    最大变化：{max(changed, key=abs):+.1f}%")
    print("若各模型变化方向一致且幅度接近，说明是环境漂移而非模型差异，相对结论仍然成立。")
else:
    print("新基线文件不完整，请检查上面的运行输出。")
PY

echo
echo "GPU 状态记录：$GPU_CSV"
if [ -f "$GPU_CSV" ]; then
  echo "（各阶段首末样本）"
  head -1 "$GPU_CSV"
  tail -n +2 "$GPU_CSV" | awk -F, 'NR<=2 || NR>=(n-2)' n="$(wc -l < "$GPU_CSV")" || true
fi
echo
echo "请把「新旧基线对照」表格与 GPU 状态尾部贴回对话。"
