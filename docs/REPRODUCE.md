# Reproduce

## 1. Deterministic checks (no GPU, no model)

```bash
python -m pip install -e ".[web,dev]" pyyaml
python scripts/verify_local.py
python scripts/validate_manifests.py   # 48 Kubernetes documents
python scripts/validate_workflows.py
python scripts/validate_docs.py
```

Expected:

- 100 passed / 7 skipped without the C-Eval archive;
- 107 passed with `CEVAL_ZIP` set;
- coverage 78.03% without C-Eval (80.03% with `CEVAL_ZIP`);
- 48 Kubernetes documents, 2 workflows, valid docs links.

## 2. Docker

```bash
docker build -f gateway/Dockerfile -t ai-inference-gateway:stable .
docker run --rm -p 9000:9000 \
  -e VLLM_BASE_URL=http://host.docker.internal:8000 \
  --add-host host.docker.internal:host-gateway \
  ai-inference-gateway:stable
```

The image installs `gateway/requirements-image.lock.txt`, then the package with
`--no-deps`.

## 3. GPU / vLLM path

Recorded environment:

| Item | Version |
|---|---|
| Host | Windows + WSL2 Ubuntu 22.04 |
| GPU | RTX 5060 8 GB, driver 595.97 |
| Runtime | vLLM 0.29.0 |
| PyTorch | 2.13.0+cu130 |
| Transformers | 5.14.1 (quantization) / 5.17.0 (serving) |
| Quantization | llm-compressor 0.13.0 |

Paths on this host:

```bash
export QWEN_BF16_DIR=/mnt/e/Desktop/subjects/qwen3.5/model/qwen3.5-4b
export QWEN_FP8_OUTPUT=/mnt/e/Desktop/subjects/qwen3.5/model/qwen3.5-4b-fp8-self-v3
export QWEN_INT4_OUTPUT=/mnt/e/Desktop/subjects/qwen3.5/model/qwen3.5-4b-int4-awq-self-v1
export CEVAL_ZIP=/mnt/e/AI-Inference-Lab/datasets/ceval.zip
```

Start vLLM with the INT4 checkpoint:

```bash
/root/.venvs/ai-inference-week1/bin/vllm serve \
  "$QWEN_INT4_OUTPUT" \
  --served-model-name Qwen3.5-4B-INT4-AWQ \
  --host 0.0.0.0 --port 8000 \
  --language-model-only --skip-mm-profiling \
  --enable-prefix-caching --enable-chunked-prefill \
  --max-model-len 2048 --max-num-seqs 16 \
  --gpu-memory-utilization 0.80
```

Start the gateway:

```bash
PYTHONPATH=src python -m llm8g.cli serve --host 127.0.0.1 --port 9029
```

Run the soak with telemetry:

```bash
python benchmark/soak_test.py \
  --url http://127.0.0.1:9029/chat \
  --duration 600 --concurrency 4 --max-tokens 32 \
  --telemetry-interval 10 \
  --output benchmark/results/soak-c4-600s.json
```

Run C-Eval:

```bash
python ceval_quality_eval.py run \
  --manifest benchmark/eval/ceval-val-200.json \
  --base-url http://127.0.0.1:8000/v1 \
  --model Qwen3.5-4B-INT4-AWQ \
  --label int4 \
  --output benchmark/eval/int4-ceval-val-200.json
```

## 4. Kubernetes

```bash
kubectl apply -k k8s
kubectl apply -k deploy/k8s-overlays/local
kubectl -n ai-inference port-forward svc/inference-gateway 9000:9000
python gateway/smoke_test.py
```

HPA/TLS demos use the in-cluster mock vLLM. See
[`K8S_VERIFICATION.md`](K8S_VERIFICATION.md).
