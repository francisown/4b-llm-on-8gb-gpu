# Scripts

The scripts fall into three groups. Check the header of each script before
running it; many experiments need a GPU, a model directory, or a running vLLM.

## Current verification and delivery

| Script | Purpose | Requirements |
|---|---|---|
| `verify_local.py` | Cost tests, gateway tests, Python syntax | Python only |
| `validate_manifests.py` | Kubernetes manifest contract checks | Python + PyYAML |
| `validate_workflows.py` | GitHub Actions YAML checks | Python + PyYAML |
| `validate_docs.py` | Markdown link and README/manifest-count checks | Python only |
| `build_quantization_csv.py` | Rebuild/check the quantization comparison CSV from raw evidence | Python only |
| `k8s_loadgen.sh` | Create the loadgen ConfigMap and run the in-cluster Job | Kubernetes |
| `kickoff`-style server scripts | Start vLLM with a specific model/profile | GPU + model weights |

## Benchmark and experiment drivers

`bench_qwen35_int4.sh`, `repeat_bench_quant.sh`, `repeat_bench_v1.sh`,
`rebuild_baseline.sh`, `run_baseline.sh`, `run_speculative_profile.sh`,
`start_chunked_prefill_experiment.sh`, `start_ngram_spec.sh`,
`start_qwen35_4b_fp8.sh`, `start_server.sh`, and `verify_v2_runner.sh` are
historical experiment drivers. They assume the original model paths and WSL2
environment; keep them for reproducibility but do not treat them as the
supported quickstart.

## Historical checks

`check_wsl2_runner.sh` and the logs under `benchmark/results/runner-verify/`
belong to the WSL2 runner investigation. The conclusion is documented in
`docs/wsl2-runner-verification.md`.

## Conventions

- Do not overwrite a raw result file; use a new protocol-specific name.
- Do not put model weights, secrets, or machine-local paths in committed output.
- If a script needs a GPU, say so in its header and in the README.
