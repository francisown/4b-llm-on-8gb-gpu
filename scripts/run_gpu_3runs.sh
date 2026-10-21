#!/usr/bin/env bash
# Run three real-vLLM batches through the gateway, entirely inside one WSL
# session. This avoids WSL killing the vLLM container when a separate shell
# command exits.
set -euo pipefail

cd /mnt/e/Desktop/temporary/ai-inference-lab
PY=/root/.venvs/ai-inference-week1/bin/python
MODEL=/mnt/e/Desktop/subjects/qwen3.5/model/qwen3.5-4b-int4-awq-self-v1

docker rm -f vllm-real gateway-real >/dev/null 2>&1 || true
docker run -d --name vllm-real --gpus all --ipc=host -p 8000:8000 \
  -e VLLM_USE_FLASHINFER_SAMPLER=0 \
  -e VLLM_WSL2_ENABLE_PIN_MEMORY=1 \
  -v "$MODEL:/model:ro" \
  ai-inference-vllm:0.29.0-cu130 /model \
  --served-model-name Qwen3.5-4B-INT4-AWQ-self \
  --max-model-len 2048 --max-num-seqs 16 --gpu-memory-utilization 0.80 \
  --enable-prefix-caching --enable-chunked-prefill >/tmp/vllm-real-3runs.log 2>&1

ready=0
for _ in $(seq 1 72); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 2 http://127.0.0.1:8000/health || true)
  if [ "$code" = "200" ]; then ready=1; break; fi
  sleep 5
done
if [ "$ready" != "1" ]; then
  echo "vLLM did not become healthy" >&2
  docker logs --tail 40 vllm-real >&2
  exit 1
fi
echo "vLLM healthy"

docker run -d --name gateway-real --link vllm-real:vllm -p 9000:9000 \
  -e VLLM_BASE_URL=http://vllm:8000 \
  -e MODEL_NAME=Qwen3.5-4B-INT4-AWQ-self \
  -e GATEWAY_VERSION=0.2.4 \
  -e POD_NAME=real-vllm-gateway \
  -e GATEWAY_RATE_LIMIT_PER_MINUTE=0 \
  ai-inference-gateway:v0.2.4 >/tmp/gateway-real-3runs.log 2>&1
sleep 4

for i in 1 2 3; do
  echo "=== non-stream run $i ==="
  "$PY" benchmark/k8s_load_test.py \
    --url http://127.0.0.1:9000/chat \
    --requests 20 --concurrency 4 --max-tokens 64 --warmup 2 \
    --prompt "Explain in one sentence why KV cache matters." \
    --output "benchmark/results/real-vllm-v0.2.4-c4-run$i.json"

  echo "=== stream run $i ==="
  "$PY" benchmark/k8s_load_test.py \
    --url http://127.0.0.1:9000/chat/stream \
    --requests 20 --concurrency 4 --max-tokens 64 --warmup 2 --stream \
    --prompt "Explain in one sentence why KV cache matters." \
    --output "benchmark/results/real-vllm-v0.2.4-stream-c4-run$i.json"
done

docker stop vllm-real gateway-real >/dev/null 2>&1 || true
echo "done"
