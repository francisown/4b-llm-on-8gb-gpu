# Developer runbook

This runbook is the short path for changing and checking the project. It keeps
the deterministic, no-GPU checks separate from experiments that need a model,
an API key, or a running vLLM server.

## Local verification

From the repository root:

```powershell
python scripts/verify_local.py
```

The command checks the repository layout, the deterministic calculator tests,
the nine gateway tests, and Python syntax. It does not start a server, download
model weights, call a model API, or run the online gateway smoke test.

The equivalent WSL command is:

```bash
python3 scripts/verify_local.py
```

## Gateway-only tests

```bash
cd gateway
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

These tests use a fake upstream service and should pass without a GPU.

## Checks that need external state

- `gateway/smoke_test.py` needs a running gateway and vLLM service.
- The C-Eval quality tests need the external `datasets/ceval.zip` archive.
- The benchmark scripts need a compatible model directory, vLLM runtime, and
  an available GPU.
- The Docker and Kubernetes paths need Docker or a cluster with the documented
  GPU and storage setup.

Do not include results from those checks in a report unless the report records
the model, runtime, GPU, driver, CUDA version, input/output lengths,
concurrency, repetitions, and repository revision.
