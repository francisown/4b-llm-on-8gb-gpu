"""Deterministic checks for the Kubernetes manifests.

This does not need a cluster. It catches the mistakes that matter for this
project: missing probes, an unsafe rollout, an unpinned image, or a
Kustomization that points at a file which no longer exists.
"""

from __future__ import annotations

from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
K8S = ROOT / "k8s"


def documents(path: Path) -> list[dict]:
    loaded = [doc for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")) if doc]
    for doc in loaded:
        if not isinstance(doc, dict):
            raise ValueError(f"{path}: expected a YAML mapping, got {type(doc).__name__}")
    return loaded


def find_document(path: Path, kind: str, name: str) -> dict:
    for doc in documents(path):
        if doc.get("kind") == kind and doc.get("metadata", {}).get("name") == name:
            return doc
    raise ValueError(f"{path}: missing {kind}/{name}")


def validate_kustomizations(errors: list[str]) -> None:
    for path in sorted(K8S.rglob("kustomization.yaml")):
        for doc in documents(path):
            for resource in doc.get("resources", []):
                target = (path.parent / resource).resolve()
                if not target.exists():
                    errors.append(f"{path}: resource does not exist: {resource}")


def validate_gateway(errors: list[str]) -> None:
    path = K8S / "deployment.yaml"
    deployment = find_document(path, "Deployment", "inference-gateway")
    spec = deployment.get("spec", {})
    strategy = spec.get("strategy", {})
    rolling = strategy.get("rollingUpdate", {})
    if strategy.get("type") != "RollingUpdate":
        errors.append("deployment: strategy.type must be RollingUpdate")
    if rolling.get("maxUnavailable") != 0:
        errors.append("deployment: rollingUpdate.maxUnavailable must be 0")
    pod_spec = spec.get("template", {}).get("spec", {})
    if pod_spec.get("terminationGracePeriodSeconds", 0) < 20:
        errors.append("deployment: terminationGracePeriodSeconds must be at least 20")
    containers = pod_spec.get("containers", [])
    if len(containers) != 1:
        errors.append("deployment: expected exactly one container")
        return
    container = containers[0]
    image = container.get("image", "")
    if not image or image.endswith(":latest") or "@" not in image and ":" not in image:
        errors.append(f"deployment: image must be pinned, got {image!r}")
    if not container.get("resources", {}).get("requests"):
        errors.append("deployment: missing resource requests")
    if not container.get("resources", {}).get("limits"):
        errors.append("deployment: missing resource limits")

    probes = {
        "readinessProbe": "/health",
        "livenessProbe": "/live",
        "startupProbe": "/live",
    }
    for probe, expected_path in probes.items():
        actual = (
            container.get(probe, {})
            .get("httpGet", {})
            .get("path")
        )
        if actual != expected_path:
            errors.append(f"deployment: {probe} must use {expected_path}, got {actual!r}")

    env = {item.get("name"): item for item in container.get("env", [])}
    if "POD_NAME" not in env:
        errors.append("deployment: POD_NAME env is missing")
    elif env["POD_NAME"].get("valueFrom", {}).get("fieldRef", {}).get("fieldPath") != "metadata.name":
        errors.append("deployment: POD_NAME must come from metadata.name")


def validate_config(errors: list[str]) -> None:
    path = K8S / "configmap.yaml"
    config = find_document(path, "ConfigMap", "inference-gateway-config")
    data = config.get("data", {})
    required = {
        "MODEL_NAME",
        "VLLM_BASE_URL",
        "GATEWAY_MAX_CONCURRENT",
        "GATEWAY_MAX_QUEUE",
        "GATEWAY_QUEUE_TIMEOUT_SECONDS",
        "UPSTREAM_TIMEOUT_SECONDS",
        "HEALTH_TIMEOUT_SECONDS",
        "UPSTREAM_CONNECT_RETRIES",
        "GATEWAY_VERSION",
    }
    missing = sorted(required - set(data))
    if missing:
        errors.append("configmap: missing keys: " + ", ".join(missing))


def main() -> None:
    errors: list[str] = []
    manifest_count = 0
    for path in sorted(K8S.rglob("*.yaml")):
        for doc in documents(path):
            manifest_count += 1
            required_fields = ["apiVersion", "kind"]
            if doc.get("kind") != "Kustomization":
                required_fields.append("metadata")
            for field in required_fields:
                if field not in doc:
                    errors.append(f"{path}: missing {field}")
                    break
            else:
                metadata = doc.get("metadata")
                if metadata is not None and not metadata.get("name"):
                    errors.append(f"{path}: missing metadata.name")

    validate_kustomizations(errors)
    validate_gateway(errors)
    validate_config(errors)

    if errors:
        print("Manifest validation failed:")
        for error in errors:
            print(" -", error)
        raise SystemExit(1)
    print(f"Manifest validation passed ({manifest_count} documents).")


if __name__ == "__main__":
    sys.exit(main())
