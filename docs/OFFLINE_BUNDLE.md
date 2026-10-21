# Offline bundle verification (local artifact)

The 7.49 GiB offline bundle referenced in the README was built and verified on
2026-10-21. **The bundle itself is not published** because it contains model
weights and a 4.2 GB image archive. This page records what was in it and the
checksums, so a copy can be verified without publishing the weights.

## Contents

Path on the build host:
`/mnt/e/Desktop/subjects/Qwen3.5-4B-INT4-Docker-Offline-20260918`

| Path | Size | Purpose |
|---|---:|---|
| `images/qwen35-local-images.tar.gz` | 4,213,941,874 B | vLLM GPU runtime and gateway image archive |
| `model/qwen3.5-4b-int4-awq-self-v1/` | 3.6 GiB | Qwen3.5-4B INT4-AWQ model |
| `compose.yaml` | 1,981 B | local Compose topology |
| `runtime-image/Dockerfile` | 651 B | runtime image definition |
| `start-local-ai.cmd`, `stop.cmd`, `status.cmd`, `logs.cmd` | scripts | one-click lifecycle |
| `verify-package.*`, `SHA256SUMS.txt` | verification | checksum check |
| `README-DEPLOY.md` | 4,499 B | clean-host deployment instructions |

Total directory size: **8,044,753,077 bytes (7.49 GiB)**.

## Checksums

```text
A972895E254CEB40405AC7BC0F0A3998416D3BFA82A5FC04596274A38D96DA35  images/qwen35-local-images.tar.gz
A11CDDBB6FADB6E45853733FE345A50ECE07839934C8110AD669FC8E55E53DEE  model/qwen3.5-4b-int4-awq-self-v1/model.safetensors
```

Machine-readable copy: [`offline-bundle-SHA256SUMS.txt`](offline-bundle-SHA256SUMS.txt).

## Verification performed

```text
Checking images\qwen35-local-images.tar.gz ...
[OK]   images\qwen35-local-images.tar.gz
Checking model\qwen3.5-4b-int4-awq-self-v1\model.safetensors ...
[OK]   model\qwen3.5-4b-int4-awq-self-v1\model.safetensors
exit=0
```

The package's `verify-package.ps1` was run on the build host; both checksums
matched.

## Limits

- This is **not** a public download. A reader can verify a copy but cannot
  obtain the weights or image archive from this repository.
- The clean-host smoke test (image import, GPU check, model startup, browser
  chat) was performed during the original build; its raw transcript is not in
  the repository.
- The bundle predates v0.2.4; its gateway image is not the latest release. If it
  is republished, rebuild/replace the gateway image and refresh the checksums.
