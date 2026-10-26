#!/usr/bin/env python3
"""Validate local Markdown links and a few generated-document invariants."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
SKIP_PREFIXES = ("http://", "https://", "mailto:", "#", "<")


def markdown_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*.md")
        if ".venv" not in path.parts
        and "node_modules" not in path.parts
        and ".git" not in path.parts
    )


def check_links() -> list[str]:
    errors: list[str] = []
    for path in markdown_files():
        text = path.read_text(encoding="utf-8")
        for match in LINK_RE.finditer(text):
            target = match.group(1).strip()
            if not target or target.startswith(SKIP_PREFIXES) or "://" in target:
                continue
            if target.startswith("{"):
                continue
            target = unquote(target.split("#", 1)[0])
            if not target:
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                line = text.count("\n", 0, match.start()) + 1
                errors.append(f"{path.relative_to(ROOT)}:{line}: missing {target}")
    return errors


def check_readme_manifest_count() -> list[str]:
    """Keep the quickstart's expected manifest count aligned with the validator."""
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    match = re.search(r"expect: (\d+) Kubernetes documents", text)
    if not match:
        return ["README.md: missing 'expect: N Kubernetes documents' quickstart line"]
    expected = int(match.group(1))
    try:
        output = __import__("subprocess").check_output(
            [sys.executable, str(ROOT / "scripts" / "validate_manifests.py")],
            cwd=ROOT,
            text=True,
            stderr=__import__("subprocess").STDOUT,
        )
    except __import__("subprocess").CalledProcessError as exc:
        return [f"README.md: validate_manifests.py failed: {exc.output.strip()}"]
    actual_match = re.search(r"\((\d+) documents\)", output)
    if not actual_match:
        return [f"README.md: could not parse manifest count from: {output.strip()}"]
    actual = int(actual_match.group(1))
    if expected != actual:
        return [
            f"README.md: expected {expected} Kubernetes documents, "
            f"validator reports {actual}"
        ]
    return []


def main() -> int:
    errors = check_links() + check_readme_manifest_count()
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"Documentation validation passed ({len(markdown_files())} files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
