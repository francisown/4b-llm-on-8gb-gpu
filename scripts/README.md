# Scripts

Deterministic checks and repository validation. None of these scripts need a
GPU, a model, or a running vLLM service.

| Script | Purpose | Requirements |
|---|---|---|
| `verify_local.py` | Run the test suite and Python syntax check | Python + test dependencies |
| `validate_manifests.py` | Validate Kubernetes manifest counts and structure | Python + PyYAML |
| `validate_workflows.py` | Validate GitHub Actions YAML | Python + PyYAML |
| `validate_docs.py` | Check Markdown links and README/manifest counts | Python |

GPU and vLLM commands live in [`../docs/REPRODUCE.md`](../docs/REPRODUCE.md).
