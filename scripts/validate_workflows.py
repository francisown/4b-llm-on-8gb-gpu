"""Validate GitHub Actions workflow YAML without contacting GitHub."""

from __future__ import annotations

from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def main() -> None:
    errors: list[str] = []
    files = sorted(WORKFLOWS.glob("*.yml"))
    if not files:
        raise SystemExit("No workflow files found")

    for path in files:
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            errors.append(f"{path.name}: invalid YAML: {exc}")
            continue
        if not isinstance(document, dict):
            errors.append(f"{path.name}: expected a mapping")
            continue
        if "on" not in document and True not in document:
            errors.append(f"{path.name}: missing 'on' trigger")
        jobs = document.get("jobs")
        if not isinstance(jobs, dict) or not jobs:
            errors.append(f"{path.name}: missing jobs")
            continue
        for name, job in jobs.items():
            if not isinstance(job, dict):
                errors.append(f"{path.name}:{name}: job is not a mapping")
                continue
            if "runs-on" not in job:
                errors.append(f"{path.name}:{name}: missing runs-on")
            steps = job.get("steps")
            if not isinstance(steps, list) or not steps:
                errors.append(f"{path.name}:{name}: missing steps")

    release = WORKFLOWS / "release.yml"
    if release.exists():
        document = yaml.safe_load(release.read_text(encoding="utf-8"))
        permissions = document.get("permissions", {}) if isinstance(document, dict) else {}
        if permissions.get("packages") != "write":
            errors.append("release.yml: permissions.packages must be 'write'")
        text = release.read_text(encoding="utf-8")
        for marker in ("docker/login-action", "docker/build-push-action"):
            if marker not in text:
                errors.append(f"release.yml: missing {marker}")

    if errors:
        print("Workflow validation failed:")
        for error in errors:
            print(" -", error)
        raise SystemExit(1)
    print(f"Workflow validation passed ({len(files)} files).")


if __name__ == "__main__":
    sys.exit(main())
