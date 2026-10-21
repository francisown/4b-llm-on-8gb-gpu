# Reproduce

This page separates three levels of reproduction. Only the first is expected to
run on a clean CPU-only machine.

## 1. Deterministic checks (no GPU, no model)

```bash
python -m pip install -r gateway/requirements-dev.txt pyyaml
python scripts/verify_local.py
python scripts/validate_manifests.py
python scripts/validate_workflows.py
python scripts/validate_docs.py
python scripts/build_quantization_csv.py --check
```

Expected: 5 cost tests, 19 gateway tests, 17 Kubernetes documents, 2 workflow
files, Markdown checks, and a CSV that matches the raw quantization evidence.

## 2. CPU-only gateway demo

```bash
bash deploy/observability/generate-certs.sh
docker compose -f deploy/observability/compose.yaml up -d --build
```

This runs a mock OpenAI-compatible upstream, the gateway, Prometheus, Grafana,
Jaeger, and an Nginx TLS terminator. It validates gateway mechanics and the
observability pipeline; it does not measure model performance. The soak and
backpressure evidence in `benchmark/results/observability/` was produced against
this mock upstream.

## 3. GPU quantization and vLLM path

Recorded environment:

| Item | Version |
|---|---|
| Host | Windows + WSL2 Ubuntu 22.04 |
| GPU | RTX 5060 8 GB, driver 595.97 |
| Runtime | vLLM 0.29.0 |
| PyTorch | 2.13.0+cu130 |
| CUDA runtime | 13.0 |
| Transformers | 5.14 |
| Quantization | llm-compressor AWQ / FP8_BLOCK, compressed-tensors + Marlin |

The original WSL2 environment is not a portable lockfile. The known versions
above are recorded for reproducibility; the exact CUDA-specific wheel set must
be installed for the target host. A recorded starting point is
[`requirements-quant.txt`](../requirements-quant.txt); it intentionally marks the
two packages whose exact versions were not captured.

### Paths

The quantization and evaluation scripts accept explicit CLI paths. They also
read these environment variables so the defaults can be overridden without
editing code:

```bash
export QWEN_BF16_DIR=/path/to/qwen3.5-4b
export QWEN_FP8_OUTPUT=/path/to/qwen3.5-4b-fp8-self-v3
export QWEN_INT4_OUTPUT=/path/to/qwen3.5-4b-int4-awq-self-v1
export CEVAL_ZIP=/path/to/ceval.zip
```

Do not commit model weights, datasets, or machine-local paths.

### Quality evaluation

```bash
# Prepare the frozen 200-question val manifest (requires C-Eval zip)
python ceval_quality_eval.py prepare \
  --ceval-zip "$CEVAL_ZIP" \
  --output benchmark/eval/ceval-val-200.json

# Evaluate a running vLLM OpenAI-compatible endpoint
python ceval_quality_eval.py run \
  --manifest benchmark/eval/ceval-val-200.json \
  --base-url http://127.0.0.1:8000/v1 \
  --model Qwen3.5-4B-INT4-AWQ-self \
  --label self-int4-awq-v1 \
  --output benchmark/eval/self-int4-awq-v1-ceval-val-200.json
```

### Quantization

```bash
python quantize_fp8_block.py \
  --model "$QWEN_BF16_DIR" \
  --output "$QWEN_FP8_OUTPUT"

python quantize_int4_awq.py \
  --model "$QWEN_BF16_DIR" \
  --output "$QWEN_INT4_OUTPUT" \
  --ceval-zip "$CEVAL_ZIP"
```

The full vLLM startup and benchmark commands are in
[`DEVELOPER_RUNBOOK.md`](DEVELOPER_RUNBOOK.md) and
[`K8S_VERIFICATION.md`](K8S_VERIFICATION.md). Historical raw JSON under
`benchmark/results/` predates the metadata checklist and may not include a git
revision, GPU driver, or CUDA version; new runs must include them
([`BENCHMARK_PROTOCOL.md`](BENCHMARK_PROTOCOL.md)).

For the WSL2 k3s GPU-in-K8s path, see
[`k8s/gpu-inference/`](../k8s/gpu-inference/). It requires an NVIDIA runtime
class and a node advertising `nvidia.com/gpu`; the recorded run used a hostPath
model and is a short smoke test, not a production PVC path.

## Known reproduction gaps

- The 7.49 GiB offline bundle contains model weights and is not published.
- A single portable lockfile for the CUDA/WSL2 quantization environment is not
  committed; the version table above is the recorded baseline.
- Stable GPU-in-Kubernetes vLLM and TensorRT-LLM results are not claimed.
