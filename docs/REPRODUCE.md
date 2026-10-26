# Reproduce

## 0. Assets

Model weights and C-Eval data are not redistributed. Put local copies outside
the repository and point the environment at them:

```bash
export QWEN_BF16_DIR="$HOME/models/qwen3.5-4b"
export QWEN_INT4_OUTPUT="$HOME/models/qwen3.5-4b-int4-awq-self-v1"
export QWEN_FP8_OUTPUT="$HOME/models/qwen3.5-4b-fp8-self-v3"
export CEVAL_ZIP="$HOME/datasets/ceval.zip"
```

The paths above are examples. Follow the upstream terms for
[Qwen3.5-4B](https://huggingface.co/Qwen) and
[C-Eval](https://github.com/SJTU-LIT/ceval). The C-Eval manifest in
`benchmark/eval/ceval-val-200.json` is frozen; the ZIP is only needed to rebuild
the manifest and to calibrate INT4-AWQ.

## 1. Deterministic checks (no GPU, no model)

```bash
python -m pip install -e ".[web,dev]" pyyaml
python scripts/verify_local.py
python scripts/validate_manifests.py   # 48 Kubernetes documents
python scripts/validate_workflows.py
python scripts/validate_docs.py
python tools/quality_stats.py          # reference paired statistics
```

Expected:

- 101 passed / 7 skipped without the C-Eval archive;
- 108 passed with `CEVAL_ZIP` set;
- coverage 78.13% without C-Eval (80.1% with `CEVAL_ZIP`);
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

## 3. Quantization

INT4-AWQ uses the C-Eval dev split for calibration and writes an
`artifact-manifest.json` next to the output:

```bash
python quantize_int4_awq.py \
  --model "$QWEN_BF16_DIR" \
  --output "$QWEN_INT4_OUTPUT" \
  --ceval-zip "$CEVAL_ZIP" \
  --samples 128 \
  --seed 20260917
```

FP8 uses the same BF16 source and a model-free block-wise PTQ path:

```bash
python quantize_fp8_block.py \
  --model "$QWEN_BF16_DIR" \
  --output "$QWEN_FP8_OUTPUT"
```

Both commands refuse to overwrite an existing output directory.

## 4. GPU / vLLM path

Recorded environment:

| Item | Version |
|---|---|
| Host | Windows + WSL2 Ubuntu 22.04 |
| GPU | RTX 5060 8 GB, driver 595.97 |
| Runtime | vLLM 0.29.0 |
| PyTorch | 2.13.0+cu130 |
| Transformers | 5.14.1 (quantization) / 5.17.0 (serving) |
| Quantization | llm-compressor 0.13.0 |

Start vLLM with the INT4 checkpoint (activate your vLLM environment first):

```bash
vllm serve "$QWEN_INT4_OUTPUT" \
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

Run the current C-Eval recheck:

```bash
python ceval_quality_eval.py run \
  --manifest benchmark/eval/ceval-val-200.json \
  --base-url http://127.0.0.1:8000/v1 \
  --model Qwen3.5-4B-INT4-AWQ \
  --label int4 \
  --output benchmark/eval/int4-ceval-val-200.json
```

The direct benchmark files are one run per concurrency; repeat before claiming
variance or a regression.

## 5. Kubernetes

```bash
kubectl apply -k k8s
kubectl apply -k deploy/k8s-overlays/local
kubectl -n ai-inference port-forward svc/inference-gateway 9000:9000
python gateway/smoke_test.py
```

The local overlay uses the locally built `stable` tag. The GHCR overlay uses
`latest` after the release workflow publishes it. HPA/TLS demos use the
in-cluster mock vLLM; see [`K8S_VERIFICATION.md`](K8S_VERIFICATION.md).

## 6. Dependency files

| File | Use |
|---|---|
| `pyproject.toml` | package plus `web`/`dev`/`quant` extras |
| `gateway/requirements-image.lock.txt` | container image (Dockerfile) |
| `requirements-quant.txt` + `.lock.txt` | quantization environment reference |
| `requirements-vllm.lock.txt` | vLLM serving environment reference |
| `gateway/requirements.txt` | direct gateway requirements used by `pip-audit` |

The locks are version-pinned, not hash-pinned. The Docker base image is pinned
by digest; dependency hashes and image signing are not part of this snapshot.
