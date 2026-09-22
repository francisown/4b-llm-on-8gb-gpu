#!/usr/bin/env bash
set -uo pipefail

profile="${1:-}"
case "$profile" in
  baseline|baselinegraph|mtp1|mtp2|mtp3|mtp4|mtp5|mtp5graph|mtp6|mtp8) ;;
  *)
    echo "usage: $0 baseline|baselinegraph|mtp1|mtp2|mtp3|mtp4|mtp5|mtp5graph|mtp6|mtp8" >&2
    exit 2
    ;;
esac

lab_dir=/mnt/e/AI-Inference-Lab
model_dir=/mnt/e/Desktop/qwen3.5/model/qwen3.5-4b-fp8
result_dir="$lab_dir/benchmark/results/speculative"
server_log="$result_dir/server-${profile}.log"

source /root/.venvs/ai-inference-bin/activate
mkdir -p "$result_dir"

# WSL on this machine cannot use the V2 runner's UVA path. The FlashInfer
# sampler also requires nvcc for its first JIT build, which is not installed.
export VLLM_USE_V2_MODEL_RUNNER=0
export VLLM_USE_FLASHINFER_SAMPLER=0

server_extra=()
if [[ "$profile" =~ ^mtp([0-9]+)(graph)?$ ]]; then
  speculative_tokens="${BASH_REMATCH[1]}"
  server_extra+=(
    --speculative-config.method mtp
    --speculative-config.num_speculative_tokens "$speculative_tokens"
  )
fi

runner_mode=(--enforce-eager)
if [[ "$profile" == *graph ]]; then
  runner_mode=()
fi

cleanup() {
  if [[ -n "${server_pid:-}" ]] && kill -0 "$server_pid" 2>/dev/null; then
    kill -TERM "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "[$profile] starting server"
vllm serve "$model_dir" \
  --served-model-name Qwen3.5-4B-FP8 \
  --host 127.0.0.1 \
  --port 8000 \
  --language-model-only \
  --skip-mm-profiling \
  --enable-prefix-caching \
  --enable-chunked-prefill \
  --max-model-len 1024 \
  --max-num-seqs 4 \
  --max-num-batched-tokens 1024 \
  --gpu-memory-utilization 0.85 \
  "${runner_mode[@]}" \
  "${server_extra[@]}" \
  >"$server_log" 2>&1 &
server_pid=$!

ready=0
for attempt in $(seq 1 36); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    ready=1
    break
  fi
  if ! kill -0 "$server_pid" 2>/dev/null; then
    break
  fi
  echo "[$profile] waiting for server ($attempt/36)"
  sleep 5
done

if [[ "$ready" -ne 1 ]]; then
  echo "[$profile] server failed to become ready" >&2
  tail -80 "$server_log" >&2
  exit 1
fi

echo "[$profile] server ready"
nvidia-smi --query-gpu=memory.used,memory.total \
  --format=csv,noheader,nounits >"$result_dir/${profile}-gpu-memory.csv"

run_bench() {
  local concurrency=$1
  local prompts=$2
  local name="${profile}-c${concurrency}"

  echo "[$profile] benchmark concurrency=$concurrency prompts=$prompts"
  if ! vllm bench serve \
    --backend openai \
    --base-url http://127.0.0.1:8000 \
    --model Qwen3.5-4B-FP8 \
    --tokenizer "$model_dir" \
    --dataset-name random \
    --random-input-len 256 \
    --random-output-len 256 \
    --num-prompts "$prompts" \
    --max-concurrency "$concurrency" \
    --ignore-eos \
    --temperature 0 \
    --seed 42 \
    --save-result \
    --result-dir "$result_dir" \
    --result-filename "${name}.json" \
    >"$result_dir/${name}.log" 2>&1; then
    tail -80 "$result_dir/${name}.log" >&2
    return 1
  fi

  grep -E \
    "Successful requests|Failed requests|Benchmark duration|Output token throughput|Mean TTFT|Mean TPOT|Mean ITL" \
    "$result_dir/${name}.log"
}

run_bench 1 8
run_bench 4 16

curl -s http://127.0.0.1:8000/metrics \
  | grep -Ei "speculat|draft|accept" \
  >"$result_dir/${profile}-metrics.txt" || true

echo "[$profile] GPU memory MiB: $(cat "$result_dir/${profile}-gpu-memory.csv")"
echo "[$profile] speculative metrics"
cat "$result_dir/${profile}-metrics.txt"
echo "[$profile] complete"
